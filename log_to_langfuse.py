import json
import sys

from dotenv import load_dotenv

load_dotenv()

from langfuse import Langfuse

if __name__ == "__main__":
    payload = json.loads(sys.stdin.read())

    lf = Langfuse()
    lf.generation(
        name=payload["name"],
        model=payload["model"],
        input=payload["input"],
        output=payload["output"],
        usage_details=payload["usage_details"],
    )
    lf.flush()
