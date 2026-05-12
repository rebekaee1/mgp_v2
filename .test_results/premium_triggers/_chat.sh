#!/bin/bash
AID="8f38186c-444f-45ad-9cad-734bd1481a59"
SID="$1"; MSG="$2"
curl -sS -X POST http://localhost:8080/api/v1/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"message\":$(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$MSG"),\"assistant_id\":\"$AID\"}"
