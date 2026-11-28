---
description: "Design of the built-in AI assistant: one chat endpoint that streams the answer, a bounded tool loop, server-rendered page buttons and flow cards, the per-screen YAML knowledge files, model settings and the answer guard."
---

# Built-in AI assistant

The assistant in the bottom-right panel is a single model with tools. Every message takes the same path: `POST /api/v1/ai/assistant/chat`. There is no intent classifier in front of it, in the browser or on the server.

The model receives the pages the signed-in user may open, the full help for the page in front of them and that page's live state. It reads help for other pages on demand, and it uses tools to attach whatever belongs under the answer. It writes the answer text; everything clickable is assembled by the server.

## One turn

1. **Context.** `app/ai/assistant/service.py` builds the system prompt from the user's role, the page catalogue, the flow list, the current screen's help and state, and the spotlight steps the browser reported.
2. **Tool loop.** Up to `assistant.max_rounds` model calls. Tools are unavailable in the last round, so the turn always ends with text. When a message already contains the answer and only attaches buttons or a card, the loop stops there instead of asking the model to speak again.
3. **Guard.** The finished answer is checked once (see [Answer guard](#answer-guard)).
4. **Response.** Text plus the attachments the tools collected.

The answer is sent to the browser while the model writes it (see [Streaming](#streaming)).

| Tool | Kind | What it does |
|---|---|---|
| `read_help` | read | Returns the full help for up to three pages |
| `get_my_requests` | read | Returns the user's own recent machine requests and their status |
| `show_pages` | action | Attaches up to four page buttons |
| `start_flow` | action | Attaches one multi-step flow card |
| `plan_machine` | action | Collects the four machine-request answers, then lets the planner fill the request form |
| `point_at` | action | Highlights one spotlight step on the current page |

The model only picks ids. Tool schemas are generated per request, and their enums contain only what this user may see, so a button can never lead to a page the user cannot open. Ids are validated again when a tool runs; an invalid id is returned to the model as an error.

The assistant never submits, creates or changes anything. `plan_machine` ends with the existing planner (`/ai/template-recommendation/recommend`) filling the request form, which the user still reviews and submits.

## Knowledge

Answers are grounded only in hand-written definitions:

| What | Where |
|---|---|
| One screen per file: purpose, when to use it, features, fields, dialogs, related pages | `backend/config/assistant/screens/<screen id>.yaml` |
| Fragments shared by several screens | `backend/config/assistant/shared/<name>.yaml` |
| Pages a button may lead to, with access level | `backend/app/ai/assistant/catalog.py` |
| Multi-step flows | `backend/app/ai/assistant/flows.py` |

Each page and screen has an access level that mirrors the route guards in `App.jsx`: `all` (any signed-in user), `learner` (students and administrators — the student course pages, which redirect teachers away), `staff` (teachers and administrators) and `admin`. The catalogue, the tool enums and the prompt only contain what the user's role may open.

The files are read at startup by `screen_files.py` and validated with Pydantic. A wrong shape, a duplicate key or a reference to a missing fragment stops the backend from starting. Editing a file takes effect after a restart.

Two ways to avoid copying text:

- `extends: <screen id>` at the top of a file starts from another screen and overrides the keys this file sets. Use it for a second URL of the same page.
- `use: <fragment>` expands a shared fragment: as a list item under `elements`, or inside a dialog to merge the fragment's `fields` and `notes`.

`order` sets the position of a screen (lower first). Order matters when one URL matches two path templates: the first match wins.

Writing rules, enforced by `backend/tests/test_ai_assistant_knowledge.py`:

- Never describe a screen position. Name the button or field instead.
- Dialog titles, the buttons that open them and field labels use the exact interface text; the tests compare them with the zh-TW locale files.
- `constraints` must match the real front-end validation.
- Related pages must be routes in the catalogue.

## Model settings

| Setting | Where | Notes |
|---|---|---|
| Endpoint, key, model | `VLLM_BASE_URL`, `VLLM_API_KEY`, `VLLM_MODEL_NAME` in `.env` | Shared by all built-in AI features |
| Model contract | `backend/config/llm-model-profiles.yaml` | The model name must have an entry |
| Assistant behaviour | `assistant` block in `backend/config/system-ai.json` | `thinking`, `max_rounds`, `timeout`, `temperature`, `top_p`, `max_tokens` |

`assistant.thinking` (default `medium`) is the reasoning level requested on every assistant call and overrides the model-wide default in the model profile. Models that only have an on/off switch treat `low`, `medium` and `high` as on.

`check_thinking: "none"` in a model profile runs the answer guard with reasoning off. Set it for models whose reasoning would overrun the guard's 128-token output limit.

## Answer guard

The generic adherence checker does not know the assistant's normal behaviour and blocked a noticeable share of correct answers in live tests. The assistant therefore passes its own prompt (`guard.py`) to the shared checker. It blocks three things only: adopting another persona, actually completing a request unrelated to SkyLab, and claiming to have submitted or changed something.

| Outcome | Reply | `degraded` |
|---|---|---|
| Allowed | The model's answer with its attachments | `false` |
| Blocked | A fixed scope message, no attachments | `false` |
| Checker unavailable | A fixed "try again" message | `true` |
| Model not configured or failing | The current page's built-in guide and its related pages | `true` |

Degraded replies are logged at `ERROR` (or `WARNING` when no model is configured).

## Streaming

The first answer to a new question takes several seconds: the model usually reads help in one round and writes in the next. So that the user is not left staring at an idle panel, `POST /api/v1/ai/assistant/chat` responds with Server-Sent Events:

| Event | Data | Meaning |
|---|---|---|
| `status` | `{"tool": …}` | The assistant has just used this tool and needs another round |
| `delta` | `{"text": …}` | Text the model is writing; append it to what is shown |
| `reset` | `{}` | Discard the text shown so far |
| `final` | The full response | Always the last event; the only one that counts |
| `error` | `{}` | Processing failed part-way; no `final` follows |

Text can only be checked once it is complete, so `delta` text is provisional. The guard runs after the last round, and the `final` event carries what stays on screen: the model's answer with its attachments, or the fixed message when the answer was blocked or could not be checked. The browser always replaces the streamed text with `final`, and only `final` is stored in the conversation. This means a blocked answer may be visible for a moment before it is replaced. That is acceptable here because the prompt holds nothing secret (only pages the user may already open), and the guard exists to keep the assistant on task, not to hide harmful content.

`reset` is sent when a round turns out not to be the answer: the model wrote something and then called a tool whose result it must respond to, for example a remark before reading help. Reasoning that a model writes inline (`<think>…</think>`) is never streamed.

Page buttons, flow cards and the other attachments arrive only with `final`.

The model call itself is streamed with `VLLMClient.stream_chat_completion`, which returns the same response shape as the non-streaming call and applies the same checks; a stream that ends without a finish reason is a failure, not a short answer. The guard still uses a single non-streaming call. When the browser disconnects, the model call is cancelled.

FastAPI adds `X-Accel-Buffering: no` and a keep-alive comment every 15 seconds. The platform's nginx honours that header and the Gateway's platform-entry server has proxy buffering off, so no proxy configuration is needed. Behind a proxy that buffers anyway, the user simply sees the whole answer at once.

## Front end

- `components/AiFloatingChat/useAssistantChat.js` sends every message with the conversation so far, the interface language and the screen context. The server keeps no conversation; the browser stores it in `sessionStorage` per user and clears it on sign-out.
- The event stream is read by `services/eventStream.js` through `apiPostEventStream` in `services/api.js` (same authentication and token refresh as every other request; `EventSource` cannot send a `POST` or an `Authorization` header). While an answer is being written, the panel shows it as the last message; the text lives in component state, not in the stored conversation. Before any text arrives, the typing indicator says what the assistant has just done.
- A page that wants the assistant to see field values and validation errors registers them with `hooks/useAiScreen`. Only the fields declared in that screen's YAML reach the prompt, and fields marked `sensitive` are reduced to "filled or not". Do not send secrets from the page in the first place.
- Spotlight: the browser sends the steps of the current page's tour that exist in the DOM. `point_at` returns one of those ids and `components/UserGuide/guideCommands.js` highlights it. Flow steps are mapped to existing `data-guide` anchors in `AiFloatingChat/flowAnchors.js`.

## Adding a page

1. Add the route to `catalog.py` if the assistant should be able to send users there.
2. Add `backend/config/assistant/screens/<id>.yaml`.
3. Add the page's spotlight tour as usual; the assistant can point at its steps without further work.
4. Run `backend/tests/test_ai_assistant_catalog.py` and `test_ai_assistant_knowledge.py`.

## Checking against a real model

`scripts/AI_live_test/system_ai_guardrails_live.py` sends probe cases to the configured model. The assistant cases go through the production entry point, so they use the assistant's prompt, tools, thinking level and guard; the request lookup is left out, so the probe never touches the database. Without `--live` it only builds and validates every request offline.

`scripts/AI_live_test/ai_assistant_live.py` asks the assistant a few navigation questions, three rounds each, and checks the page buttons it attaches: for example, it must not attach a button for the page the user is already on. Its report records, for every model call, how long it took and when the first text arrived. Read the first round of each case for timing: a model gateway may cache identical requests, which makes the repeated rounds much faster than a real first question.

Run both after changing the prompt, the tools or the model. Their offline tests live in `scripts/AI_live_test/tests/` (`cd backend && uv run pytest ../scripts/AI_live_test/tests`).
