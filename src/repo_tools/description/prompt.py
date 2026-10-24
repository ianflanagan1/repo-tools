"""What a model is asked when it writes a repo's description, and what of its reply is kept.

The two are one contract: the prompt asks for one plain sentence within the limit, and
description() keeps a reply only when it is one.
"""

MAX_FILES = 300
MAX_DOCUMENT_CHARACTERS = 6000
QUOTES = "\"'`"

PROMPT = """\
Write the description shown under a source code repository's name on GitHub: one sentence \
saying what the project is and does, for someone deciding whether to look further.

- At most {max_length} characters.
- Plain text: no Markdown, emoji or surrounding quotes.
- Say what it is, not how good it is: no words such as "powerful", "seamless" or "modern".
- Don't start with "This repository", "A repository" or the project's name.

Reply with the sentence alone.

Repository: {name}

Tracked files:
{files}
{documents}"""


def prompt(name: str, files: list[str], documents: dict[str, str], max_length: int) -> str | None:
    """The prompt for the repo called name, given its tracked files and the text of the
    documents among them that say what it is; None when it has no files to describe."""
    if not files:
        return None
    listed = "\n".join(files[:MAX_FILES])
    if len(files) > MAX_FILES:
        listed += f"\n(and {len(files) - MAX_FILES} more)"
    shown = "".join(
        f"\n--- {path} ---\n{text[:MAX_DOCUMENT_CHARACTERS]}\n" for path, text in documents.items()
    )
    return PROMPT.format(max_length=max_length, name=name, files=listed, documents=shown)


def description(reply: str, max_length: int) -> str | None:
    """The reply as one line without surrounding quotes, or None when that's empty or longer
    than max_length."""
    text = " ".join(reply.split())
    while len(text) > 1 and text[0] == text[-1] and text[0] in QUOTES:
        text = text[1:-1].strip()
    if not text.strip(QUOTES) or len(text) > max_length:
        return None
    return text
