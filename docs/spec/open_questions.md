# Open Questions (for stakeholder sign-off)

1. **Exact input limits.** Are 50 MB/file, 8000x8000 px, 100 PDF pages and
   50 files/batch the right defaults for your production documents and
   HMI photos?
2. **Coil table variants.** How many distinct factory coil-table layouts
   exist today? Sample images per layout are needed before P4 profiles.
3. **ID format ground truth.** Real HOT_COIL_NO / COLD_COIL_NO formats and
   plausible ranges for THICK/WIDTH/WEIGHT/LENGTH - the current regexes and
   ranges are placeholders to confirm.
4. **Language scope.** Vietnamese + English only, or other languages
   (Chinese, Korean) expected on machine labels?
5. **External API policy.** Is Gemini Vision permitted at all in your
   environment, and if so for which document classes?
6. **Retention periods.** Are the 7-day input retention and
   keep-results-until-deleted defaults acceptable?
7. **Ground-truth data.** Can real production images (blur, glare, skew
   included) be shared into the benchmark set, and under what access rule?
8. **TEDS vs adjacency F1.** Should table structure also report TEDS in P3,
   or is adjacency F1 sufficient for acceptance?
