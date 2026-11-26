# RAG Travel Planner Experiment Report

## Task and method

The assistant accepts a destination, departure date, duration, total per-person budget and audience. The Gradio interface calls `trip_profile`, which derives northern-hemisphere seasonal context and supported Chinese holiday/rest-day information. Unknown holiday-calendar years remain unconfirmed. Daily budget describes spending level rather than limiting daily expenses.

Every submission calls `collect_guides` with fresh trip-specific queries. The browser reads accessible Xiaohongshu search cards and matching detail text through the dedicated Edge session. Search states distinguish loading, explicit empty results, login, verification, restrictions and parse errors. DOM content is preferred; page-loaded initial state is read only for the requested note ID. Title-only records are preserved but excluded from body evidence.

If fewer than three readable articles are available, broader searches and Trip.com destination directories supplement the evidence with same-city travel posts. Canonical URLs and body hashes remove duplicates. The target is at least three distinct bodies and at most five; inaccessible sites cannot be guaranteed. Retrieved passages, source numbers and trip constraints are supplied to Qwen. This lightweight retrieval approach needs no vector database for each small, freshly fetched evidence set.

## Generation and budget

Qwen returns route sections and explicit unit-price assumptions. The program validates that a complete itinerary object exists, then renders seven fixed sections. `budget.py` is the single Decimal-based ledger: accommodation is price per room per night times rooms and nights; personal charges multiply people; vehicle charges first form group costs and then divide by people. Reserve is counted once. Budget differences and total spend are computed by code, not recalculated in model prose.

The form does not collect party size or room count, so the displayed budget is explicitly a single-person, single-room conditional scenario. Audience labels never imply two-person sharing. Intercity travel and airport/station transfers are excluded by default. Unconfirmed prices, discounts, routes and weather remain assumptions or verification tasks. Only source-supported statements receive numbered citations; all provided evidence links are listed with uncited material labelled as general reference.

## Implementation and analysis

`start.py -> app.generate_ui -> app.generate -> trip_profile -> collect_guides -> planner.plan -> calculate_budget` is the user-facing path. The existing `/generate` API retains a single Markdown response. The visible progress bar follows completed retrieval work and generated character counts, with model-stage percentages explicitly estimated. It reaches 100 percent after rendering and citation processing.

Run the offline suite with `python -m unittest discover -s test -p "test_*.py" -v`. It checks budget bases, unknown group assumptions, source deduplication and supplementation, exact-ID extraction, source propagation, output structure, model streaming and monotonic visible progress. Standalone network checks are in `test/test_qwen.py` and `test/test_crawler.py`. The detailed commands and environment setup are in README.md.

For qualitative evaluation, compare itinerary statements with their cited passages, inspect daily geographic grouping, verify slow-paced rest options, and recompute budget rows from their price bases. No benchmark accuracy, live inventory, or guaranteed real-time pricing is claimed. Previously observed keyword-search restrictions and API-format differences have regression tests; real service availability can change independently of those tests.

## Sharing and limitations

Conda uses Python 3.12 and requirements.txt pins direct runtime dependencies to versions tested during development. The repository includes an owner-authorized shared demonstration configuration. Environment variables override that configuration for personal use. Shared API quota, Cookie validity, model access and website network restrictions limit availability. A successful local run does not guarantee another user's network or account will work. The code does not bypass access challenges or fabricate signatures; logging omits credential values.

Packaging validation: all 46 offline tests passed. With both model-key environment variables removed, the shared model configuration returned a live response. A new temporary Edge profile, without pre-existing cookies, imported the shared configuration and read three real Xiaohongshu note bodies. These checks are point-in-time validation, not a guarantee of ongoing account or website availability.
