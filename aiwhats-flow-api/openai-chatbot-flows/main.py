import os
import re
import uuid
import aiohttp
import asyncio
from dotenv import load_dotenv
from quart import Quart, jsonify, request
import openai
import logging
import aio_pika
import json

app = Quart(__name__)

# Configurações e variáveis de ambiente
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
AUTH_TOKEN_CHATWOOT = os.getenv("AUTH_TOKEN_CHATWOOT_WEBHOOK")
WEBHOOK_URLS = [
    os.getenv("N8N_WEBHOOK_URL"),
    os.getenv("CHATWOOT_WEBHOOK_URL"),
    os.getenv("CRM_WEBHOOK_URL"),
]
RABBITMQ_URI = os.getenv("RABBITMQ_URI")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE")
RABBITMQ_ROUTING_KEY = os.getenv("RABBITMQ_ROUTING_KEY") or ""
RABBITMQ_ENABLED = os.getenv("RABBITMQ_ENABLED", "false") == "true"

# Configure o logger
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicialize a API OpenAI
openai.api_key = OPENAI_API_KEY

async def forward_to_webhook(webhook_url, body):
    headers = {"Content-Type": "application/json"}
    if webhook_url == CHATWOOT_WEBHOOK_URL and AUTH_TOKEN_CHATWOOT:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN_CHATWOOT}"

    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, headers=headers, json=body) as response:
            if response.status != 200:
                error_message = await response.text()
                logger.error("Error forwarding to webhook", extra={"error": error_message, "webhookUrl": webhook_url})
                return
            responseData = await response.json()
            logger.info("Webhook forwarding response", extra={"webhookUrl": webhook_url, "responseData": responseData})

async def main():
    # Example usage of forward_to_webhook function
    body = {"key": "value"}  # Replace this with the actual data you want to forward
    await forward_to_webhook(CHATWOOT_WEBHOOK_URL, body)
    
async def send_to_rabbitmq(payload):
    if not RABBITMQ_ENABLED:
        logger.info("RabbitMQ is not enabled")
        return

    connection = await aio_pika.connect_robust(RABBITMQ_URI)
    async with connection:
        channel = await connection.channel()
        
        # Declare an exchange of type 'topic' and a durable queue
        exchange = await channel.declare_exchange(RABBITMQ_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue(RABBITMQ_QUEUE, durable=True, arguments={"x-queue-type": "quorum"})
        
        # Bind the queue to the exchange with the routing key
        await queue.bind(exchange, RABBITMQ_ROUTING_KEY)
        
        # Publish the message to the exchange with the specified routing key
        await exchange.publish(
            aio_pika.Message(body=json.dumps(payload).encode()),
            routing_key=RABBITMQ_ROUTING_KEY
        )
        
        logger.info("Message sent to RabbitMQ", extra={"payload": payload})

async def main():
    # Example payload
    payload = {"key": "value"}  # Replace this with the actual data you want to send
    await send_to_rabbitmq(payload)
            
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
TOKEN = os.getenv("TOKEN")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
code_prompt_texts = ["Entre em contato", "Converse com nosso Assistants IA", "SIM", "NÃO"]

service_list = [
    "Inteligência Artificial Conversacional",
    "Desenvolvimento Web",
    "Automações",
    "Consultoria",
    "Mentoria"
]

app = Quart(__name__)

@app.route('/webhook', methods=['GET'])
async def webhook_get():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("WEBHOOK_VERIFIED")
        response = make_response(challenge, 200)

        # Forwarding verification to Chatwoot if CHATWOOT_WEBHOOK_URL is set
        if CHATWOOT_WEBHOOK_URL:
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {AUTH_TOKEN_CHATWOOT}'
                }
                chatwoot_response = requests.get(CHATWOOT_WEBHOOK_URL, headers=headers, params={
                    "hub.mode": mode, "hub.verify_token": token, "hub.challenge": challenge
                })
                chatwoot_response.raise_for_status()
                chatwoot_data = chatwoot_response.json()
                logger.info("Chatwoot verification forwarded", extra={"chatwootData": chatwoot_data})
            except Exception as e:
                logger.error("Error forwarding verification to Chatwoot", extra={"error": str(e)})

        return response
    else:
        logger.warn("Webhook verification failed")
        return make_response("Forbidden", 403)


@app.route("/webhook", methods=["POST"])
async def webhook_post():
    try:
        body = await request.json
        logger.info("Webhook received", extra={"body": body})

        async with aiohttp.ClientSession() as session:
            tasks = [forward_to_webhook(session, url, body) for url in WEBHOOK_URLS if url]
            await asyncio.gather(*tasks)

        asyncio.create_task(send_to_rabbitmq(body))
        
        if request.method == "POST":
            request_data = json.loads(request.get_data())
            if (
                request_data["entry"][0]["changes"][0]["value"].get("messages")
            ) is not None:
                name = request_data["entry"][0]["changes"][0]["value"]["contacts"][0][
                    "profile"
                ]["name"]
                if (
                    request_data["entry"][0]["changes"][0]["value"]["messages"][0].get(
                        "text"
                    )
                ) is not None:
                    message = request_data["entry"][0]["changes"][0]["value"]["messages"][
                        0
                    ]["text"]["body"]
                    user_phone_number = request_data["entry"][0]["changes"][0]["value"][
                        "contacts"
                    ][0]["wa_id"]
                    user_message_processor(message, user_phone_number, name)
                else:
                    # checking that there is data in a flow's response object before processing it
                    if (
                        request_data["entry"][0]["changes"][0]["value"]["messages"][0][
                            "interactive"
                        ]["nfm_reply"]["response_json"]
                    ) is not None:
                        flow_reply_processor(request)

        return make_response("PROCESSED", 200)

    except Exception as e:
        logger.error("Error in POST /webhook", extra={"error": str(e)})
        return "", 500

def flow_reply_processor(request):
    request_data = json.loads(request.get_data())
    name = request_data["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"][
        "name"
    ]
    message = request_data["entry"][0]["changes"][0]["value"]["messages"][0][
        "interactive"
    ]["nfm_reply"]["response_json"]

    flow_message = json.loads(message)
    flow_key = flow_message["flow_key"]
    if flow_key == "agentconnect":
        firstname = flow_message["firstname"]
        reply = f"Obrigado por entrar em contato {firstname}. Um agente entrará em contato com você o mais breve possível."
    else:
        firstname = flow_message["firstname"]
        secondname = flow_message["secondname"]
        issue = flow_message["issue"]
        reply = f"Sua resposta foi registrada. Isso é o que recebemos:\n\n*NOME*: {firstname} {secondname}\n*SUA MENSAGEM*: {issue}"

    user_phone_number = request_data["entry"][0]["changes"][0]["value"]["contacts"][0][
        "wa_id"
    ]
    send_message(reply, user_phone_number, "FLOW_RESPONSE", name)


def extract_string_from_reply(user_input):
    match user_input:
        case "1":
            user_prompt = code_prompt_texts[0].lower()
        case "2":
            user_prompt = code_prompt_texts[1].lower()
        case "S":
            user_prompt = code_prompt_texts[2].lower()
        case "N":
            user_prompt = code_prompt_texts[3].lower()
        case _:
            user_prompt = str(user_input).lower()

    return user_prompt


def user_message_processor(message, phonenumber, name):
    user_prompt = extract_string_from_reply(message)
    if user_prompt == "sim":
        send_message(message, phonenumber, "TALK_TO_AN_AGENT", name)
    elif user_prompt == "não":
        print("Chat finalizado")
    else:
        if re.search("serviço", user_prompt):
            send_message(message, phonenumber, "SERVICE_INTRO_TEXT", name)

        elif re.search(
            "ajuda|contato|chegar|e-mail|problema|questão|mais|informação", user_prompt
        ):
            send_message(message, phonenumber, "CONTACT_US", name)

        elif re.search("olá|oi|saudações", user_prompt):
            if re.search("isto", user_prompt):
                send_message(message, phonenumber, "CHATBOT", name)

            else:
                send_message(message, phonenumber, "SEND_GREETINGS_AND_PROMPT", name)

        else:
            send_message(message, phonenumber, "CHATBOT", name)


def send_message(message, phone_number, message_option, name):
    greetings_text_body = (
        "\nOlá "
        + name
        + ". Bem-vindo ao Setup Automatizado. Como podemos ajudá-lo?\nPor favor, responda com um número entre 1 e 2.\n\n1. "
        + code_prompt_texts[0]
        + "\n2. "
        + code_prompt_texts[1]
        + "\n\nQualquer outra resposta irá conectá-lo ao nosso Assistants IA."
    )

    # loading the list's entries into a string for display to the user
    services_list_text = ""
    for i in range(len(service_list)):
        item_position = i + 1
        services_list_text = (
            f"{services_list_text} {item_position}. {service_list[i]} \n"
        )

    service_intro_text = f"We offer a range of services to ensure a comfortable stay, including but not limited to:\n\n{services_list_text}\n\nWould you like to connect with an agent to get more information about the services?\n\nY: Yes\nN: No"

    contact_flow_payload = flow_details(
        flow_header="Contate-nos",
        flow_body="Você indicou que gostaria de nos contatar.",
        flow_footer="Clique no botão abaixo para prosseguir",
        flow_id=str("<FLOW-ID>"),
        flow_cta="Prosseguir",
        recipient_phone_number=phone_number,
        screen_id="CONTACT_US",
    )

    agent_flow_payload = flow_details(
        flow_header="Falar com um Agente",
        flow_body="Você indicou que gostaria de falar com um agente para obter mais informações sobre os serviços que oferecemos.",
        flow_footer="Clique no botão abaixo para prosseguir",
        flow_id=str("<FLOW-ID>"),
        flow_cta="Prosseguir",
        recipient_phone_number=phone_number,
        screen_id="TALK_TO_AN_AGENT",
    )

    match message_option:
        case "SEND_GREETINGS_AND_PROMPT":
            payload = json.dumps(
                {
                    "messaging_product": "whatsapp",
                    "to": str(phone_number),
                    "type": "text",
                    "text": {"preview_url": False, "body": greetings_text_body},
                }
            )
        case "SERVICE_INTRO_TEXT":
            payload = json.dumps(
                {
                    "messaging_product": "whatsapp",
                    "to": str(phone_number),
                    "type": "text",
                    "text": {"preview_url": False, "body": service_intro_text},
                }
            )
        case "CHATBOT":
            # criar um prompt de texto
            prompt = message
            # gerar uma resposta usando o modelo GPT-3.5 da OpenAI
            response = openai.Completion.create(
                engine="gpt-3.5-turbo-1106",
                prompt=prompt,
                max_tokens=250
            )
            output_text = response.choices[0].text.strip()
            payload = json.dumps({
                "messaging_product": "whatsapp",
                "to": str(phone_number),
                "type": "text",
                "text": {"preview_url": False, "body": output_text}
            })
        case "CONTACT_US":
            payload = contact_flow_payload
        case "TALK_TO_AN_AGENT":
            payload = agent_flow_payload
        case "FLOW_RESPONSE":
            payload = json.dumps(
                {
                    "messaging_product": "whatsapp",
                    "to": str(phone_number),
                    "type": "text",
                    "text": {"preview_url": False, "body": message},
                }
            )

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + ACCESS_TOKEN,
    }

    requests.request("POST", url, headers=headers, data=payload)
    print("MESSAGE SENT")


def flow_details(
    flow_header,
    flow_body,
    flow_footer,
    flow_id,
    flow_cta,
    recipient_phone_number,
    screen_id,
):
    # Generate a random UUID for the flow token
    flow_token = str(uuid.uuid4())

    flow_payload = json.dumps(
        {
            "type": "flow",
            "header": {"type": "text", "text": flow_header},
            "body": {"text": flow_body},
            "footer": {"text": flow_footer},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": flow_token,
                    "flow_id": flow_id,
                    "flow_cta": flow_cta,
                    "flow_action": "navigate",
                    "flow_action_payload": {"screen": screen_id},
                },
            },
        }
    )

    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(recipient_phone_number),
            "type": "interactive",
            "interactive": json.loads(flow_payload),
        }
    )
    return payload
if __name__ == '__main__':
    app.run(debug=True, port=5000)
