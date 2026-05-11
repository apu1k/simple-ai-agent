from openai import OpenAI

from llm.models import ModelConfig


def create_client(model_config: ModelConfig):
    if model_config.base_url:
        return OpenAI(
            api_key=model_config.api_key,
            base_url=model_config.base_url,
        )

    return OpenAI(api_key=model_config.api_key)


def convert_messages_for_responses_api(messages):
    instructions = []
    input_messages = []

    for message in messages:
        role = message.get("role")
        content = message.get("content", "")

        if role == "system":
            instructions.append(content)
        elif role in {"user", "assistant"}:
            input_messages.append({
                "role": role,
                "content": content,
            })

    return "\n\n".join(instructions), input_messages


def chat_with_chat_completions(messages, model_config: ModelConfig):
    client = create_client(model_config)

    response = client.chat.completions.create(
        model=model_config.model,
        messages=messages,
    )

    return response.choices[0].message.content


def chat_with_responses_api(messages, model_config: ModelConfig):
    client = create_client(model_config)
    instructions, input_messages = convert_messages_for_responses_api(messages)

    response = client.responses.create(
        model=model_config.model,
        instructions=instructions,
        input=input_messages,
    )

    return response.output_text


def chat(messages, model_config: ModelConfig):
    if model_config.api_type == "responses":
        return chat_with_responses_api(messages, model_config)

    if model_config.api_type == "chat_completions":
        return chat_with_chat_completions(messages, model_config)

    raise ValueError(f"Unsupported API type: {model_config.api_type}")