from core_ai.content import (
    IMAGE_TOKEN_ESTIMATE,
    estimate_content_tokens,
    image_part,
    normalize_content,
    sniff_image_media_type,
    split_text_and_images,
    text_from_content,
    to_anthropic_blocks,
    to_gemini_parts,
    to_openai_chat_content,
    to_openai_responses_content,
)


PNG_B64 = "aaa"


def _image(**kwargs: object) -> dict[str, object]:
    return image_part(media_type="image/png", data=PNG_B64, filename="shot.png", **kwargs)


def test_normalize_accepts_openai_and_anthropic_image_shapes() -> None:
    canonical = normalize_content(
        [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": "bbb"},
            },
        ]
    )
    assert canonical[0] == {"type": "text", "text": "look"}
    assert canonical[1]["type"] == "image"
    assert canonical[1]["data"] == PNG_B64
    assert canonical[1]["media_type"] == "image/png"
    assert canonical[2]["media_type"] == "image/jpeg"
    assert canonical[2]["data"] == "bbb"


def test_provider_payloads_translate_canonical_images() -> None:
    content = [{"type": "text", "text": "what is this?"}, _image()]

    chat = to_openai_chat_content(content)
    assert chat[0] == {"type": "text", "text": "what is this?"}
    assert chat[1]["type"] == "image_url"
    assert chat[1]["image_url"]["url"] == f"data:image/png;base64,{PNG_B64}"

    responses = to_openai_responses_content(content)
    assert responses[0] == {"type": "input_text", "text": "what is this?"}
    assert responses[1] == {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{PNG_B64}",
    }

    anthropic = to_anthropic_blocks(content)
    assert anthropic[0] == {"type": "text", "text": "what is this?"}
    assert anthropic[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": PNG_B64},
    }

    gemini = to_gemini_parts(content)
    assert gemini == [
        {"text": "what is this?"},
        {"inlineData": {"mimeType": "image/png", "data": PNG_B64}},
    ]


def test_http_image_urls_keep_provider_native_references() -> None:
    content = [
        {
            "type": "image",
            "media_type": "image/jpeg",
            "url": "https://example.com/cat.jpg",
            "filename": "cat.jpg",
        }
    ]

    chat = to_openai_chat_content(content)
    assert chat[0]["image_url"]["url"] == "https://example.com/cat.jpg"

    responses = to_openai_responses_content(content)
    assert responses[0] == {
        "type": "input_image",
        "image_url": "https://example.com/cat.jpg",
    }

    anthropic = to_anthropic_blocks(content)
    assert anthropic[0]["source"] == {"type": "url", "url": "https://example.com/cat.jpg"}

    gemini = to_gemini_parts(content)
    assert gemini[0] == {
        "fileData": {"mimeType": "image/jpeg", "fileUri": "https://example.com/cat.jpg"}
    }


def test_string_content_stays_a_string_for_openai() -> None:
    assert to_openai_chat_content("hello") == "hello"
    assert to_openai_responses_content("hello") == "hello"


def test_text_and_token_helpers_do_not_dump_image_bytes() -> None:
    huge = "a" * 50_000
    content = [
        {"type": "text", "text": "see"},
        image_part(media_type="image/png", data=huge, filename="shot.png"),
    ]
    assert text_from_content(content) == "see\n[image:shot.png]"
    tokens = estimate_content_tokens(content)
    assert tokens == IMAGE_TOKEN_ESTIMATE + 1
    assert huge not in text_from_content(content)


def test_sniff_image_media_type_uses_suffix_and_magic() -> None:
    assert sniff_image_media_type(b"", filename="shot.GIF") == "image/gif"
    assert sniff_image_media_type(b"\x89PNG\r\n\x1a\nxxxx") == "image/png"
    assert sniff_image_media_type(b"GIF89a....") == "image/gif"
    assert sniff_image_media_type(b"not an image", filename="notes.txt") is None


def test_split_text_and_images_keeps_tool_text_and_parts() -> None:
    text, images = split_text_and_images(
        [{"type": "text", "text": "Read image shot.png"}, _image()]
    )
    assert text == "Read image shot.png"
    assert images[0]["data"] == PNG_B64
    assert images[0]["filename"] == "shot.png"
