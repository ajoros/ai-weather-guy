# WeatherNext DOs and DON’Ts

Compiled 18 September 2026 from every **substantive** link on [Terms of service and disclaimers](https://developers.google.com/weathernext/guides/disclaimers). This is a working reading of those documents, not legal advice. If a use is not clearly permitted, email [weathernext@google.com](mailto:weathernext@google.com) before doing it.

**Clock that decides the license:** look at the **valid time of the data** (the weather time the field is about), not when you downloaded it.

| Valid time of the data | License |
| --- | --- |
| Less than 1 hour ago, or any future time | [GDM Real-Time Weather Forecasting Experimental Data Terms of Use](https://storage.googleapis.com/weathernext-public/terms-of-use.pdf) (PDF last modified **3 September 2026**) |
| 1 hour ago or older | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — real-time data **auto-flips** when it ages past 1 hour |

The current PDF and the developer docs now both use **1 hour**. Older copies of that PDF (November 2025) said 48 hours. Use the live PDF.

By accessing or querying the data, or deploying WeatherNext models, you agree to the applicable terms.

---

## 1. Applies to every product

These come from the [disclaimers page](https://developers.google.com/weathernext/guides/disclaimers), the GDM PDF §6, Earth Engine catalogs, Weather Lab, and the [open-source README](https://github.com/google-deepmind/weathernext).

### DO

- Treat the outputs as **experimental research / informational** data.
- Defer to national meteorological services and local emergency authorities for life-and-property decisions.
- Assume you are solely responsible for whether a use is appropriate.
- Keep third-party upstream terms in mind (ECMWF / ERA5 / HRES, Copernicus, IBTrACS, etc.). Those sit **on top of** Google’s license. See [acknowledgements](https://developers.google.com/weathernext/guides/acknowledgements).
- Email [weathernext@google.com](mailto:weathernext@google.com) for access problems, late runs, or any use not clearly permitted.

### DON’T

- Do **not** treat WeatherNext as official forecasts, watches, or warnings.
- Do **not** rely on it as a **sole** source for life or property.
- Do **not** claim Google, DeepMind, or any meteorological agency **sponsors, endorses, or grants official status** to you or your product.
- Do **not** make accuracy claims to third parties that conflict with the terms.
- Do **not** present the data as consumer-grade or “validated for real-world use.” The required citations say the opposite.

The GDM PDF also says the real-time data is approximate, provided **as-is**, **not intended for consumer use**, and Google’s aggregate liability is capped at **USD 500**. If you are a legal entity, you indemnify Google for third-party claims from unlawful use or breach (except to the extent caused by Google’s breach, negligence, or willful misconduct).

---

## 2. Quick matrix (which bucket are you in?)

| What you want to do | Real-time / future fields | Historical fields (≥ 1 h old) | WN2 on Gemini Enterprise / Vertex | Open-source WN2 / Gen / Graph |
| --- | --- | --- | --- | --- |
| Use internally (research, ops, product R&D) | Yes, if eligible | Yes | Yes, if project is allowlisted | Yes |
| Publish a derived map / paper / viz that cannot recover the raw grid | Yes, with GDM citation | Yes, with CC BY attribution | Extra Cloud AI/ML restrictions | Yes, with Apache / CC BY notices |
| Redistribute raw or near-raw grids publicly (API, dump, email blast, social) | **No** | Yes, if you keep CC BY attribution and do not add lock-in | **No** (and competing-product ban) | Code: Apache. Weights/non-code: CC BY |
| Train / distill a competing weather model from the outputs | Ask Google; Cloud path **forbids** this | CC BY is copyright-only — still do not ignore Cloud terms if you used Cloud inference | **Forbidden** | Weights are CC BY; still experimental, not a license to impersonate Google |
| Use as the public warning service | **No** | **No** | **No** | **No** |

---

## 3. Real-time and future data (GDM terms)

Source: [terms-of-use.pdf](https://storage.googleapis.com/weathernext-public/terms-of-use.pdf) (3 September 2026). Covers Earth Engine, BigQuery, Weather Lab, GCS buckets, and any other page that links to those terms.

The license Google grants is **non-exclusive, royalty-free, revocable, non-transferable, and non-sublicensable** except as the PDF expressly allows.

You must also follow [Google’s Generative AI Prohibited Use Policy](https://policies.google.com/terms/generative-ai/use-policy).

### 3.1 Who may use it

**DO**

- Use it if you have legal capacity to accept the terms.
- If using for a company, bind that company (you warrant you have authority).
- Keep the name / entity / contact details you gave Google **correct and current**. Update via weathernext@google.com.
- Expect Google to ask for identity / entity verification.

**DON’T**

- Do **not** accept or use the data if you lack capacity (including age).
- Do **not** accept if doing so would breach another contract or third-party right.
- Do **not** use it if you are a resident of, or ordinarily resident in, a **Restricted Country**, or if export/sanctions law bars you, unless Google agrees **in writing** (email counts).
- Do **not** make the data available **in** a Restricted Country, unless Google agrees in writing.

Restricted countries named in the PDF: **Japan, South Korea, Indonesia, Cuba, Iran, North Korea, Crimea, and the so-called Donetsk and Luhansk People’s Republics**.

### 3.2 Allowed purposes (only these)

You may access, use, and **modify** real-time experimental data **solely** for:

1. **Any internal purpose.**
2. Creating and sharing a **Value Added Service (VAS)** under §3 of the PDF (see §3.3 below).
3. Sharing the real-time data itself with:
   - clearly identified third parties, via **controlled distribution that does not enable onward sharing**, and **only for educational purposes**;
   - your **Subsidiaries** (you hold a majority of voting rights);
   - **Contractors** who have a contract to provide services **to you** that require access.

**DON’T**

- Do **not** treat “I downloaded it, so I can post the Zarr / run a public API of unmodified grids” as allowed. That is the opposite of a VAS (see below).
- Do **not** sublicense or transfer the raw feed except through the three sharing channels above.
- Do **not** add extra contract terms that **conflict** with the GDM terms.

If you want a use outside those three purposes, the PDF says to contact weathernext@google.com.

### 3.3 What counts as a Value Added Service

A VAS is a product, service, graphic, visualisation, or other material that is **both**:

1. derived from or based on the real-time data, **and**
2. created for a **specific purpose or use case that cannot be achieved** by using the real-time data separately from that service.

Google will not claim ownership of your VAS. Google **does** reserve the right to build its own.

These are **not** a VAS. The PDF treats them as **unmodified real-time data**:

- a service that merely lets people access, download, or retrieve unmodified data (web, file, P2P, email, VPN, social, API);
- recoloring, formatting, compressing;
- a fixed or arbitrary **percentage** adjustment;
- geometric transformation;
- subsetting areas;
- custom combinations of time-steps, parameters, or model runs.

**Practical read:** a public “WeatherNext mirror,” a thin API of the same fields, or a recolored 2 m temperature map of the raw grid is **not** a VAS. A flood model, energy-dispatch tool, or store-risk score that **needs** your extra logic **and** from which the raw WN3 grid cannot cheaply be recovered is closer to a VAS.

### 3.4 Sharing a VAS

**Non-retrievable VAS** — the real-time data cannot be retrieved or reverse-engineered without significant technical effort or expense.

- **DO** share it with third parties, including by **publication**.
- **DO** attach the findings / non-retrievable citation in §3.6.

**Retrievable VAS** — the real-time data **can** be recovered without significant effort.

- **DO** share only by **controlled transmission** to **clearly identified and known** third parties.
- Those parties may use it **only for their own internal purposes**.
- **DON’T** let them share it onward.
- **DON’T** let them use it to generate another VAS.
- Subsidiaries and contractors are included in this controlled path.
- Attach the extra notices in §3.5.

### 3.5 Notices you must attach when sharing real-time data or a retrievable VAS

All of these:

1. A copy of the GDM Terms.
2. A “Legally Binding Terms of Use” text file that says:

   > By using this information, you agree to the Terms of Use found at https://storage.googleapis.com/weathernext-public/terms-of-use.pdf

3. A prominent copyright notice: `Copyright 2024-6 Google LLC`
4. Notice of **any modifications you made**.

**DON’T** add conflicting extra terms.

### 3.6 Citation when you publish findings or a non-retrievable VAS

Cite the Google product/service you used to access the data, plus:

> © 2024-6 Google LLC, whose machine learning models were used to create the experimental data made available under the following licence terms https://storage.googleapis.com/weathernext-public/terms-of-use.pdf. This data is intended for experimental modelling only and is not intended, validated, or approved for real world use.

### 3.7 Other real-time DON’Ts

- Do **not** use the data or a VAS in a way that breaks these Terms or the [Generative AI Prohibited Use Policy](https://policies.google.com/terms/generative-ai/use-policy) (illegal activity, CSAM, non-consensual intimate imagery, violent extremism, self-harm facilitation, unconsented tracking, high-risk automated decisions without human supervision, malware/phishing, hate, harassment, scams, deceptive impersonation, fake official/health expertise, claiming generated content is purely human-made in order to deceive, etc.).
- Do **not** use Google’s trademarks, trade names, or logos, or imply endorsement.
- Do **not** keep using the feed if you reject a posted change to the terms or a future fee. You **may** keep using copies accessed **before** the change, under the old terms, to keep providing a VAS — unless Google suspended or terminated you.
- If Google **terminates** you: **delete** real-time data and VASs in your possession; **notify** recipients to stop; **do not** re-apply.

Google may suspend or terminate for breach, change or discontinue the data (they will try to give reasonable notice), update the terms (usually 14 days; legal/functionality changes immediate), and later charge **reasonable fees** with at least **one month’s** written notice. Access is currently free. Feedback you send can be used with no obligation to you. Governing law: **California**, exclusive venue **Santa Clara County**, unless local law requires otherwise.

EEA / Switzerland counterparties contract with **Google Ireland Limited**; everyone else with **Google LLC**.

---

## 4. Historical data (CC BY 4.0)

Source: [CC BY 4.0 deed](https://creativecommons.org/licenses/by/4.0/) and [legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en). Trigger: valid time **≥ 1 hour ago**.

This is a **copyright** license. It does not erase the “not an official forecast” duty, ECMWF/third-party terms, or Cloud AI/ML restrictions if you generated the fields on Vertex / Gemini Enterprise.

### DO

- **Share** — copy and redistribute in any medium or format, including commercially.
- **Adapt** — remix, transform, and build on the material, including commercially.
- Extract and reuse a substantial portion of the database (sui generis database rights, where they exist).
- When you share (including modified form), **attribute**:
  - creator / designated attribution parties;
  - copyright notice;
  - license notice + link to CC BY 4.0;
  - disclaimer-of-warranty notice;
  - a URI/link to the material where practicable;
  - **indicate if you modified** it and keep prior modification notes.
- Use the Earth Engine catalog citation when you disclose findings from historical WN3 0.1° data:

  > © 2026 DeepMind Technologies Limited's machine learning models used to create the experimental data made available at https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p1deg under CC BY 4.0 licence terms. This data is intended for experimental modelling only and is not intended, validated, or approved for real world use.

  Use the matching 0.05° catalog URL if that is the collection you used.

### DON’T

- Do **not** imply Google / DeepMind endorses you.
- Do **not** apply extra legal terms or **effective technological measures** that stop others from doing what CC BY allows (no “you may have this NetCDF but you cannot reshare it”).
- Do **not** assume CC BY grants **patent or trademark** rights. It does not.
- Do **not** skip attribution. Failure can **terminate** your CC BY rights automatically (cure within 30 days of discovery can reinstate).
- Do **not** treat CC BY as a warranty. Material is as-is; no fitness-for-purpose promise.

---

## 5. WeatherNext models on Google Cloud (managed inference)

Sources: [disclaimers](https://developers.google.com/weathernext/guides/disclaimers), [Cloud Service Specific Terms §17](https://cloud.google.com/terms/service-terms#1), [access-vmg](https://developers.google.com/weathernext/guides/access-vmg), [working-vmg](https://developers.google.com/weathernext/guides/working-vmg).

This path is **WeatherNext 2 only**. WeatherNext 3 is **not** the on-demand Model Garden model. You need a **separate project allowlist**, billing, Vertex / Gemini Enterprise Agent Platform API, IAM, and GPU quota (default quota is 0).

### DO

- Use custom initial conditions, ensemble size, horizon, and hourly output if the notebooks expose those flags.
- Write outputs to **your** GCS bucket as Zarr.
- Use a Persistent Resource with the **default** Agent Platform Custom Code Service Agent (custom service accounts are **not** supported for WN2 jobs).
- Follow Cloud AUP and the [Generative AI Prohibited Use Policy](https://policies.google.com/terms/generative-ai/use-policy).

### DON’T (disclaimers page + access-vmg + Cloud §17)

- Do **not** use WeatherNext models or the forecasts they generate to develop a **similar or competing product or service**. Google may suspend immediately on suspicion.
- Do **not** use outputs to **substitute, replace, or circumvent** the models, directly or indirectly.
- Do **not** use outputs to **create or improve models similar to** WeatherNext / a Google Model, except authorised fine-tuning / distillation where the service actually offers that feature.
- Do **not** reverse engineer or extract model components (including fishing for training data).
- Do **not** treat Cloud §17(a)’s “Vertex exception” as a free pass: that exception is only if you **do not** use a **Google Pre-Trained Model**. WeatherNext 2 on Model Garden **is** a Google pre-trained model.

Generative AI extras that can also apply on Cloud: no service directed at or likely accessed by people **under 18**; no **clinical** use (non-clinical research / admin is called out as OK).

---

## 6. Open-source models (not WeatherNext 3)

Sources: [osmodel](https://developers.google.com/weathernext/guides/osmodel), [GitHub README](https://github.com/google-deepmind/weathernext), [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**WeatherNext 3 is not open source.** You cannot download WN3 weights. You consume WN3 as operational forecast data under the GDM / CC BY split above.

What *is* in the repo: WeatherNext 2 (and Mini / Cyclones), WeatherNext Gen, WeatherNext Graph. Weights on `gs://dm_graphcast`.

### DO

- Use, modify, and redistribute **code and Colabs** under **Apache 2.0** (include the license, state changes, keep notices / NOTICE file).
- Use **non-code materials and weights** under **CC BY 4.0** (attribution; no extra lock-in).
- Cite the papers if you publish research (WN2 / Cyclones / Gen / Graph citations are in the README).
- Pin a release; the README says the API is not stable.
- Check ERA5 / HRES / WeatherBench2 terms before training.

### DON’T

- Do **not** expect this repo to give you WeatherNext 3.
- Do **not** treat it as an officially supported Google product.
- Do **not** treat self-hosted output as official warnings.
- Do **not** skip Apache / CC BY notices on redistribution.
- Do **not** assume Apache grants trademark rights.
- Do **not** ignore ECMWF / Copernicus / IBTrACS terms on training or sample data.

---

## 7. Weather Lab

Source: [Weather Lab guide](https://developers.google.com/weathernext/guides/weatherlab).

### DO

- View global layers (WN3 / WN2 / MetNet) and cyclone tracks in the browser.
- Download **experimental cyclone** tracks (CSV / ATCF), including ensemble and paired observations.
- Apply the same 1-hour GDM vs CC BY split to downloads.

### DON’T

- Do **not** treat Lab downloads as an officially supported Google product or as official cyclone warnings.

---

## 8. Docs site itself (not the forecast grids)

Source: [Google Developers Site Policies](https://developers.google.com/site-policies) (footer link on the disclaimers page).

### DO

- Reuse WeatherNext **documentation text** under CC BY 4.0 with attribution and a link back.
- Reuse **code samples** in the docs under Apache 2.0.

### DON’T

- Do **not** reuse Google trademarks / brand features under that license.
- Do **not** assume images, audio, video, or off-site embeds are covered unless marked.

---

## 9. Technical “don’t treat this as truth” (benefits & limitations)

Source: [Benefits and limitations](https://developers.google.com/weathernext/guides/benefits-limitations). Not a license, but it tells you where the model is known to be wrong-looking.

### DO

- Prefer **ensemble statistics** (mean, quantiles, exceedance) for many applications.
- Bias-correct if you need close agreement with station observations. WN3 station heads help; they do not erase the issue.
- For flood-style work, the docs say **pooled / spatially aggregated** precip skill is the intended use of the experimental satellite-radar head, not pretty single-member maps.

### DON’T

- Do **not** treat a single ensemble member of `experimental_tp_1hr` as a clean radar image — hexagonal mesh artifacts are expected; worse than IMERG; still visible in the mean, less so in the median.
- Do **not** assume station-head series are smooth across 6-hour windows — jumps and a **per-sample global warm/cold bias** that resets every 6 hours are documented.
- Do **not** assume operational WN3 matches the research-paper scores one-for-one.

---

## 10. Practical cheatsheet for this project

You have allowlist access to **operational forecast datasets** (EE / BQ / GCS), not automatically to **WN2 managed inference**.

Safe first uses:

- Pull a **historical** slice (valid time ≥ 1 hour old), keep the CC BY citation, use it internally.
- Build internal notebooks, bias checks, and derived scores.
- If you later publish a **non-retrievable** product (a risk score, a downscaled field that cannot cheaply invert to the WN3 grid), use the GDM citation while any input is still “real-time,” then CC BY once it ages.

Ask Google before:

- A public API or bucket of unmodified or lightly reformatted **real-time** fields.
- Training another weather model on WN3 / WN2 outputs.
- Shipping a consumer weather app that looks like an official forecast.
- Any use from or into a Restricted Country.
- Anything that needs to be an official warning path.

---

## 11. Sources (every substantive link on the disclaimers page)

| Link | Role |
| --- | --- |
| [Disclaimers page](https://developers.google.com/weathernext/guides/disclaimers) | Hub: experimental disclaimer, 1-hour split, Cloud model bans |
| [GDM terms PDF](https://storage.googleapis.com/weathernext-public/terms-of-use.pdf) | Binding rules for real-time / future data |
| [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) / [legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en) | Historical data |
| [Cloud Service Specific Terms](https://cloud.google.com/terms/service-terms#1) §17 | Competing-product, substitute/circumvent, reverse-engineering |
| [Open source models](https://developers.google.com/weathernext/guides/osmodel) | WN3 is not OSS; Apache / CC BY split |
| [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0) | OSS code / Colabs / docs samples |
| [Site policies](https://developers.google.com/site-policies) | Docs-page reuse |
| [weathernext@google.com](mailto:weathernext@google.com) | Exceptions, access, termination updates |

Follow-on pages those documents point at and used above: [Generative AI Prohibited Use Policy](https://policies.google.com/terms/generative-ai/use-policy), [access-vmg](https://developers.google.com/weathernext/guides/access-vmg), [working-vmg](https://developers.google.com/weathernext/guides/working-vmg), [benefits-limitations](https://developers.google.com/weathernext/guides/benefits-limitations), [weatherlab](https://developers.google.com/weathernext/guides/weatherlab), [GitHub weathernext](https://github.com/google-deepmind/weathernext), [WN3 0.1° catalog citations](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p1deg).

Nav-only links on the same HTML page (models, GCS, BQ, EE, glossary, etc.) describe **how to get data**, not extra license grants. They are inventoried in `WEATHERNEXT3_DATA.md`.
