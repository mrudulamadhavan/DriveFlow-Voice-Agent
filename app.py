import json
import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_gsheets import GSheetsConnection
from huggingface_hub import InferenceClient
from datetime import datetime

st.set_page_config(page_title="DriveFlow AI Voice Sales Bot", page_icon="🚗", layout="wide")

# ---------- Secrets ----------
AGENT_ID = st.secrets.get("ELEVENLABS_AGENT_ID", "")
EL_KEY = st.secrets.get("ELEVENLABS_API_KEY", "")
N8N_URL = st.secrets.get("N8N_WEBHOOK_URL", "")
HF_KEY = st.secrets.get("HUGGINGFACE_API_KEY", "")

# ---------- Session state ----------
if "credits_exhausted" not in st.session_state:
    st.session_state.credits_exhausted = False
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------- Languages ----------
LANGS = {
    "English": {
        "code": "en",
        "first": "Hello! This is Alex from DriveFlow. Thanks for picking up.",
    },
    "Hindi (हिंदी)": {
        "code": "hi",
        "first": "नमस्ते! मैं ड्राइवफ़्लो से एलेक्स बोल रहा हूँ। कॉल उठाने के लिए धन्यवाद।",
    },
    "Telugu (తెలుగు)": {
        "code": "te",
        "first": "నమస్తే! నేను డ్రైవ్‌ఫ్లో నుండి అలెక్స్‌ని. కాల్ ఎత్తినందుకు ధన్యవాదాలు.",
    },
}

STATUS_ICON = {
    "Converted": "🟢", "Demo Requested": "🟣", "Interested": "🔵",
    "Follow-up Required": "🟡", "Not Interested": "🔴", "No Response": "⚪",
}

# ---------- Voice widget ----------
VOICE_WIDGET = """
<style>
  body{font-family:system-ui,sans-serif;margin:0;color:#222}
  .row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
  button{padding:10px 18px;border:0;border-radius:8px;font-size:15px;cursor:pointer;color:#fff}
  #start{background:#16a34a} #end{background:#dc2626} button:disabled{opacity:.4;cursor:not-allowed}
  #status{padding:6px 12px;border-radius:8px;background:#eee;font-size:14px;flex:1}
  #chat{height:300px;overflow-y:auto;border:1px solid #ddd;border-radius:8px;padding:10px;background:#fafafa}
  .m{margin:6px 0;padding:8px 12px;border-radius:12px;max-width:85%;font-size:14px;line-height:1.4}
  .agent{background:#e0ecff} .user{background:#e7f7e7;margin-left:auto}
  small{color:#777}
</style>
<div class="row">
  <button id="start">🚀 Start Call</button>
  <button id="end" disabled>🛑 End Call</button>
  <div id="status">⚪ Idle</div>
</div>
<div id="chat"><small>Tick the consent box, then press Start Call. Allow microphone access when asked.</small></div>
<script type="module">
import { Conversation } from 'https://esm.sh/@elevenlabs/client';
const CFG = __CONFIG__;
const $ = id => document.getElementById(id);
let conv = null, timer = null, t0 = 0, convId = null;
const fmt = s => String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
const setStatus = t => $('status').textContent = t;
const add = (who, text) => {
  const d = document.createElement('div');
  d.className = 'm ' + who; d.textContent = (who==='agent'?'🤖 ':'👤 ') + text;
  const c = $('chat'); if (c.querySelector('small')) c.innerHTML = '';
  c.appendChild(d); c.scrollTop = c.scrollHeight;
};
function tick(label){ timer = setInterval(()=>setStatus(label+' | ⏱️ '+fmt(Math.floor((Date.now()-t0)/1000))),1000); }

$('start').onclick = async () => {
  if (!CFG.consent) { setStatus('⚠️ Please tick the recording consent box first'); return; }
  try {
    await navigator.mediaDevices.getUserMedia({audio:true});
    setStatus('🟡 Connecting...');
    conv = await Conversation.startSession({
      agentId: CFG.agentId,
      connectionType: 'webrtc',
      overrides: { agent: { language: CFG.lang, firstMessage: CFG.first } },
      onConnect: () => { t0 = Date.now(); tick('🟢 Connected ('+CFG.langName+')'); $('start').disabled = true; $('end').disabled = false; },
      onMessage: m => add(m.source === 'ai' ? 'agent' : 'user', m.message),
      onError: e => setStatus('❌ ' + (e.message || e)),
      onDisconnect: () => finish(),
    });
    convId = conv.getId();
  } catch (e) { setStatus('❌ ' + e.message); }
};
$('end').onclick = async () => { if (conv) await conv.endSession(); };

async function finish() {
  if (!timer) return;
  clearInterval(timer); timer = null;
  const dur = fmt(Math.floor((Date.now()-t0)/1000));
  setStatus('⚪ Call ended ('+dur+') — generating summary...');
  $('start').disabled = false; $('end').disabled = true;
  if (CFG.n8n && convId) {
    fetch(CFG.n8n, {method:'POST', mode:'no-cors', headers:{'Content-Type':'text/plain'},
      body: JSON.stringify({conversation_id: convId, duration: dur, language: CFG.langName,
                            date: new Date().toISOString().slice(0,16).replace('T',' ')})});
  }
  setTimeout(()=>setStatus('✅ Saved. Refresh the history panel in ~30s.'), 1500);
}
</script>
"""

# ---------- Header ----------
st.title("🚗 DriveFlow — Multilingual AI Voice Sales Agent")
st.caption("Voice: ElevenLabs Agents · Automation: n8n · Storage: Google Sheets")
st.markdown("---")

col_live, col_db = st.columns([45, 55], gap="large")

# ---------- DB connection ----------
conn = st.connection("gsheets", type=GSheetsConnection)


# ---------- Helpers ----------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_recording(conv_id: str):
    r = requests.get(
        f"https://api.elevenlabs.io/v1/convai/conversations/{conv_id}/audio",
        headers={"xi-api-key": EL_KEY},
        timeout=30,
    )
    return r.content if r.status_code == 200 else None


@st.cache_resource
def get_hf_client():
    if not HF_KEY:
        return None
    return InferenceClient(token=HF_KEY)


def append_chat_to_google_sheet(user_query, text_reply):
    """Append one row to Call_History (conn.create would try to make a NEW worksheet)."""
    try:
        new_row = {
            "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Conversation ID": "Chat-Fallback",
            "Language": "English",
            "Duration": "N/A (Text Chat)",
            "Sales Status": "Interested",
            "Executive Summary": "Text-based fallback live session conversation log.",
            "Requirements": user_query,
            "Objections": "None recorded via text pipeline.",
            "Next Steps": "Follow up with customer regarding interest parameters.",
            "Transcript": f"User: {user_query}\nAgent: {text_reply}",
        }
        existing = conn.read(worksheet="Call_History", ttl=0).dropna(how="all")
        updated = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)
        conn.update(worksheet="Call_History", data=updated)
        st.cache_data.clear()
    except Exception as data_err:
        print(f"Spreadsheet write failed: {data_err}")


def query_opensource_llama(user_message):
    client = get_hf_client()
    if not client:
        return "Fallback model unavailable: HUGGINGFACE_API_KEY is missing in secrets."

    system_prompt = (
        "You are a polite, helpful AI sales representative for DriveFlow. "
        "Provide short responses (under 3 sentences)."
    )
    messages = [{"role": "system", "content": system_prompt}]
    # session_state.messages already ends with the current user message
    for m in st.session_state.messages[-5:]:
        messages.append({"role": m["role"], "content": m["content"]})

    try:
        completion = client.chat.completions.create(
            model="meta-llama/Llama-3.1-8B-Instruct",
            messages=messages,
            max_tokens=200,
            temperature=0.7,
        )
        model_reply = completion.choices[0].message.content
        append_chat_to_google_sheet(user_message, model_reply)
        return model_reply
    except Exception as api_err:
        print(f"HF error: {api_err}")
        return "Sorry, the assistant is temporarily unavailable. Please try again."


# ---------- Left panel ----------
with col_live:
    st.subheader("📞 Live Interaction Panel")

    # Bind checkbox directly to session state so it can be turned off again
    st.sidebar.checkbox("Simulate ElevenLabs Credit Depletion", key="credits_exhausted")

    if not st.session_state.credits_exhausted:
        lang_name = st.selectbox("🌐 Conversation language", list(LANGS.keys()))
        consent = st.checkbox("I consent to this call being recorded and transcribed.")

        if not AGENT_ID:
            st.error("Set ELEVENLABS_AGENT_ID in secrets.")

        cfg = {
            "agentId": AGENT_ID,
            "n8n": N8N_URL,
            "consent": consent,
            "lang": LANGS[lang_name]["code"],
            "first": LANGS[lang_name]["first"],
            "langName": lang_name.split(" ")[0],
        }
        components.html(VOICE_WIDGET.replace("__CONFIG__", json.dumps(cfg)), height=430)
    else:
        st.error("⚠️ ElevenLabs voice credits exhausted. Switched to Chat System Fallback.")
        st.markdown("---")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if chat_input_query := st.chat_input("Voice channels are down. Type support query here..."):
            with st.chat_message("user"):
                st.markdown(chat_input_query)
            st.session_state.messages.append({"role": "user", "content": chat_input_query})

            with st.spinner("Processing through Llama 3.1 fallback line..."):
                processed_reply = query_opensource_llama(chat_input_query)

            with st.chat_message("assistant"):
                st.markdown(processed_reply)
            st.session_state.messages.append({"role": "assistant", "content": processed_reply})

# ---------- Right panel ----------
with col_db:
    st.subheader("📊 Cloud Logs")

    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

    tab_hist, tab_slots = st.tabs(["📈 Call History", "🗓️ Test-Drive Bookings"])

    with tab_hist:
        try:
            df = conn.read(worksheet="Call_History", ttl="5s").dropna(how="all")
            if df.empty:
                st.info("No logs recorded yet.")
            for i, row in df.iloc[::-1].iterrows():
                status = str(row.get("Sales Status", "No Response"))
                icon = STATUS_ICON.get(status, "⚪")
                title = (
                    f"{icon} {row.get('Date', '')} [{row.get('Language', '')}] "
                    f"— {status} ({row.get('Duration', '')})"
                )
                with st.expander(title):
                    conv_id = str(row.get("Conversation ID", "")).strip()
                    st.markdown("🔊 Recording")
                    if conv_id and conv_id != "nan" and "Chat" not in conv_id:
                        if st.button("▶️ Load recording", key=f"rec_{i}"):
                            audio = fetch_recording(conv_id)
                            if audio:
                                st.audio(audio, format="audio/mpeg")
                            else:
                                st.warning(
                                    "Recording not available yet (or audio saving is disabled on the agent)."
                                )
                    elif "Chat" in conv_id:
                        st.caption("🎵 Session interaction processed entirely over text fallback line.")
                    st.write(f"Summary: {row.get('Executive Summary', 'N/A')}")
                    st.write(f"Customer requirements: {row.get('Requirements', 'N/A')}")
                    st.write(f"Objections: {row.get('Objections', 'N/A')}")
                    st.write(f"Next steps: {row.get('Next Steps', 'N/A')}")
                    st.markdown("📄 Transcript")
                    st.text(str(row.get("Transcript", "N/A")))
        except Exception as e:
            st.error(f"Could not read 'Call_History': {e}")

    with tab_slots:
        try:
            st.dataframe(
                conn.read(worksheet="Test_Drive_Slots", ttl="5s"),
                use_container_width=True,
                hide_index=True,
            )
        except Exception as e:
            st.error(f"Could not read 'Test_Drive_Slots': {e}")
