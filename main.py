import os
from slack import WebClient
from slackeventsapi import SlackEventAdapter
import requests
from flask import Flask
from dotenv import load_dotenv
import concurrent.futures

load_dotenv()
app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PERSPECTIVE_API_KEY = os.getenv("PERSPECTIVE_API_KEY")

def get_moderation_response(content):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    data = {
        "input": content
    }

    response = requests.post("https://api.openai.com/v1/moderations", json=data, headers=headers)
    return response.json()

def get_perspective_api_response(content):
    url = "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze"

    data = {
        "comment": {"text": content},
        "languages": ["en"], 
        "requestedAttributes": {"TOXICITY": {}},
        "doNotStore": True
    }

    params = {
        "key": PERSPECTIVE_API_KEY
    }

    response = requests.post(url, json=data, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

def send_to_slack(channel, message, thread_ts=None):
    try:
        slack_client = WebClient(token=SLACK_BOT_TOKEN)
        bot_name = "toxicity_alert"
        response = slack_client.chat_postMessage(channel=channel, text=message, thread_ts=thread_ts, username=bot_name)
        return response["message"]["ts"]
    except Exception as e:
        print(f"Error posting message: {e}")
        return None

def handle_message(channel, text, ts=None):
    perspective_response = get_perspective_api_response(text)
    openai_response = get_moderation_response(text)

    perspective_result = None
    openai_result = None

    if perspective_response and 'attributeScores' in perspective_response and 'TOXICITY' in perspective_response['attributeScores']:
        toxicity_score = perspective_response['attributeScores']['TOXICITY']['summaryScore']['value']
        perspective_result = {"toxicity_score": toxicity_score}

    if openai_response.get("results"):
        flagged = openai_response["results"][0].get("flagged")
        categories = openai_response["results"][0].get("categories", {})

        if flagged:
            toxic_categories = [category for category, value in categories.items() if value is True]
            toxic_categories_str = ", ".join(toxic_categories)
            openai_result = {"toxic_categories": toxic_categories_str}

    if perspective_result or openai_result:
        message = "Toxic content detected in the conversation."
        if perspective_result:
            message += f" Perspective API : {perspective_result}\n"
        if openai_result:
            message += f" OpenAI : {openai_result}"

        send_to_slack(channel, message, thread_ts=ts)


def listen_to_slack():
    slack_client = WebClient(token=SLACK_BOT_TOKEN)
    slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, endpoint="/slack/events")

    @slack_events_adapter.on("message")
    def handle_slack_message(event_data):
        message = event_data["event"]
        if "subtype" not in message:  
            channel = message["channel"]
            text = message.get("text", "")
            bot_id = message.get("bot_id", "")
            ts = message.get("ts")
           
            if not bot_id:
                handle_message(channel, text, ts)

    port = int(os.environ.get("PORT", 5000))
    slack_events_adapter.start(port=port, host="0.0.0.0")

if __name__ == "__main__":
    listen_to_slack()
