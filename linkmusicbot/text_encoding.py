"""Repair reversible UTF-8 mojibake, leaving valid names intact."""
import re


def repair_text(value):
    def repair_token(token):
        for _ in range(2):
            if not any(marker in token for marker in ("Ã", "Â", "Å", "Ð", "Ñ", "â", "ã", "å", "æ", "ð", "ç", "è", "é", "ä")):
                break
            for encoding in ("latin1", "cp1252"):
                try:
                    fixed = token.encode(encoding).decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
                token = fixed
                break
            else:
                break
        return token
    fixed = repair_token(value)
    if fixed != value:
        return fixed
    return "".join(repair_token(token) for token in re.split(r"([ \t\r\n]+)", value))
