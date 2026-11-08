"""
Nandhini Stationery - Input Sanitization & Anti-XSS Engine
Cleanses user inputs, prevents Cross-Site Scripting (XSS), and neutralizes script injection.
"""
import re
import html


def sanitize_text(text: str, max_length: int = None) -> str:
    """
    Sanitizes user input by stripping dangerous tags and escaping HTML entities.
    Safely prevents stored and reflected XSS attacks.
    """
    if not text:
        return ""

    val = str(text).strip()

    # Strip dangerous HTML and script tags
    val = re.sub(
        r'<\s*(script|iframe|object|embed|svg|style|applet|form|link|meta)[^>]*>.*?<\s*/\s*\1\s*>',
        '',
        val,
        flags=re.IGNORECASE | re.DOTALL
    )
    # Strip standalone self-closing tags and event attributes like onerror=, onload=
    val = re.sub(r'<\s*[^>]+>', '', val)
    val = re.sub(r'on\w+\s*=', '', val, flags=re.IGNORECASE)
    val = re.sub(r'javascript:\s*', '', val, flags=re.IGNORECASE)

    # Escape HTML special characters (&, <, >, ", ')
    val = html.escape(val)

    if max_length and len(val) > max_length:
        val = val[:max_length]

    return val

