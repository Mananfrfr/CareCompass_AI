# CareCompass AI — From Medical Concern to Coordinated Care

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)

![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**Hospital finder and health-insurance navigation for India.** Tell CareCompass your health concern, a known
condition, or paste the key lines of a medical report, plus your city (and insurer, if you have one). It:

1. Checks the message for emergency warning signs first. If it finds any, it gives emergency guidance (112 / 108) and stops.
2. Works out which hospital service fits the concern (e.g. ACL tear → orthopaedics, kidney stone → urology). This is navigation, not a diagnosis.
3. Sends the work to two specialist agents: a **Hospital Verification Agent** and an **Insurer Research Agent**.
4. Matches their evidence and flags conflicts, such as one insurer source listing a hospital and another de-listing it.
5. Ranks options with an explainable score, then runs an independent verifier that removes any unsupported claim.
6. Shows a shortlist card with sources and dates. You open the evidence and **approve** before anything is saved.
7. Saves the approved shortlist, reads it back to verify it, and returns a real reference ID (e.g. `CC-7KQ2M9XD`).

## Try saying

- "I have an ACL tear. I live in Jaipur and have Demo Shield insurance. Help me find a suitable hospital."
- "I have kidney stones and live in Delhi."
- "I've had knee pain for two weeks." (CareCompass will ask only for your city.)
- "Find in-network hospitals for cataract surgery in Delhi."

## What it will never do

- Diagnose you, or recommend medicines.
- Say a treatment is "covered". A network listing is not the same as plan eligibility or claim approval, and CareCompass keeps these separate.
- Book appointments, or contact hospitals or insurers.
- Invent hospitals, sources or confirmation numbers.

## Data

- **Demo mode** uses clearly labelled *synthetic* hospitals and fictional insurers ("Demo Shield Insurance", "Sample Care Health"), so the full workflow can be shown reproducibly.
- **Live mode** uses OpenStreetMap (ODbL), hospitals' own websites, and official insurer network lists imported by the operator.

Commands: `new search`, `retry`, `show CC-XXXXXXXX`, `delete my data`.

_CareCompass helps you navigate care. It does not diagnose and does not guarantee insurance coverage. Confirm with the hospital and your insurer before treatment. In an emergency, call 112._
