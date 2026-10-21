# 🚗 DriveFlow — Multilingual AI Voice Sales Agent 

  DriveFlow is a multilingual AI voice sales agent. It phones car dealerships, talks to the sales/showroom head by voice, answers questions, and tries to convert them into a demo booking. Here we chose to sell a test-drive scheduling SaaS, but the same system can sell any SaaS product by changing the prompt and the knowledge base.

## Requirements

- Python 3.9 or newer
- An ElevenLabs Agent configured for the app
- A Google Sheets spreadsheet and service-account credentials
- An n8n webhook for call-ended notifications

## Architecture Diagram

 <img width="1266" height="738" alt="image" src="https://github.com/user-attachments/assets/1d10c3a4-539c-477c-b804-94b436091b3f" />

### Working Pipeline 
- Live call: The customer talks through the voice widget embedded in your Streamlit app. The widget opens a WebRTC session straight to the ElevenLabs agent, which handles speech-to-text, the LLM reply and text-to-speech.

- After the call : When the session disconnects, the widget sends the conversation_id, duration, language and date to your n8n webhook. n8n then fetches the transcript from ElevenLabs, summarises it and sets the sales status, objections and next steps. It writes the result to the Call_History sheet in Google Sheets.

- Dashboard : The Streamlit dashboard / app reads these worksheets to display call history, bookings, and knowledge-base data through the GSheets connection. When you click “Load recording”, it also calls the ElevenLabs audio endpoint using the API key kept in server-side secrets.




