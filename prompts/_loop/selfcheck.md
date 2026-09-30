# Self-check: spec requirements

Check the assembled page source against every requirement in the page spec. Judge from the code itself: a requirement is present if the source implements it.

## Page spec
{{spec}}

## Assembled page source (every file)
{{source}}

Reply with only this JSON object, one entry per spec requirement:
{"requirements": [{"requirement": "<requirement>", "present": true|false, "evidence": "<file and component that implements it, or exactly what is missing>"}]}
