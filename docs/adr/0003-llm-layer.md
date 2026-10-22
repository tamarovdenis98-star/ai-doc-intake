# ADR 0003: Provider-agnostic LLM layer with masking, schemas and a budget

**Status:** accepted (stage 6)

## Decision
- `LLM_PROVIDER` (`rules` | `gigachat` | `yandex` | `openai`) selects the provider; a request may override it
  (used by eval to compare providers on the same documents). GigaChat, YandexGPT and OpenAI all expose an
  OpenAI-compatible `/chat/completions`, so there is one client; providers differ only in auth (GigaChat OAuth
  with the Russian root CA, Yandex `Api-Key` + folder model URI, OpenAI Bearer) and in structured-output support
  (`response_format: json_schema` where available, JSON requested in the prompt for GigaChat).
- `temperature 0`; the answer must validate against `schemas/<doc_type>.schema.json` (JSON Schema 2020-12);
  one repair call with the schema errors, then the result is stored with its errors and routed to review.
- **Personal data is masked before leaving** (`app/mask.py`): people, phones, e-mails, personal INN, passports,
  SNILS, cards and bank accounts become placeholders like `[PERSON_1]`; the model copies them; the service puts
  the values back. A guard refuses to call an external provider if a personal-data pattern is still present.
- **Budget per document**: tokens and roubles of all calls in one processing pass are summed in `documents`;
  over `llm_max_tokens_per_doc` / `llm_max_cost_rub_per_doc` the service answers 409 and the document goes to a human.
- `rules` is a deterministic provider (keywords and regular expressions for known layouts): no keys, no cost;
  it keeps the pipeline usable and testable without keys and is the baseline in the eval comparison.

## Measured baseline (`rules`, 56 documents, stage 6)
Classification 100 %, fields 83.2 % (scans 83.8 %), line items exact 72.5 %, 17/40 clean documents auto,
8/8 defective documents to review, 0 defective documents auto.
