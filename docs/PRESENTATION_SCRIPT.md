# Kai Check Oʻahu — Presentation Script and Q&A

About 3–4 minutes spoken. **A** = Person A (data and model), **B** = Person B (app).
Numbers come from `models/model.json` and `PLAN.md`. Before you present, rewrite each line
in your own words. Judges can tell when someone is reading.

---

## Script

**B — The hook (≈30 s)**
> Picture a sunny Saturday after a rainy week. You take your little brother to the beach.
> The water looks fine, but it might be full of bacteria from sewage and runoff. Nobody
> told you, because the state tests most beaches only every couple of weeks, and its Brown
> Water Advisories go out mainly after big floods. We built **Kai Check Oʻahu** so anyone
> can find out in five seconds whether the water at their beach is likely safe today.

**A — The problem and the data (≈45 s)**
> The bacteria we track is called *enterococcus*. It's how Hawaiʻi's Department of Health
> tells whether water has fecal contamination. Above 130 per 100 mL, the water counts as
> unsafe to swim in.
> Volunteers with Surfrider's Blue Water Task Force have tested Oʻahu beaches for years.
> We downloaded their whole archive: about 3,700 samples from 63 sites. We kept 9 popular
> swimming beaches from 2018 on. That's about 1,270 samples, and roughly 30% of them were
> unsafe.

**A — How the model works (≈50 s)**
> Rain is the main cause. It washes runoff from streams and storm drains into the ocean.
> For every lab sample, we looked up the weather from the days *before* it was taken: rain
> over the past week, days since the last rain, temperature, and wind. We used only
> weather from before each sample, so the model never "peeks" at the answer.
> The model predicts how much bacteria to expect at each beach, then turns that into a
> chance that the water is over the safety limit. We wrote the training math ourselves,
> using gradient descent in Python.
> To test it fairly, we trained on 2018–2024 and graded it on 2025–26 samples it had never
> seen.

**A — Results (≈30 s)**
> The model caught **80% of the unsafe days** in the test years. A rule that only warns
> during flash-flood-level rain caught **4%**. We're honest about what drives this:
> *which beach* explains a lot on its own, and weather makes the prediction noticeably
> sharper on top of that.

**B — Demo (≈60 s)** *(live at safebeachesoahu.streamlit.app; have a screen recording
ready in case the Wi-Fi fails)*
> Every time you open the app, it pulls today's live weather forecast. Pick a beach and
> you get one big number: the chance the water is unsafe, colored as lower risk, caution,
> or likely unsafe.
> Under that is the "why": for example, "lots of rain this week." Then a 3-day outlook, so
> you can plan the weekend, and a plain "What should I do?" box. If your beach is risky,
> it suggests a safer one nearby.
> The map shows every beach at a glance. You can sign up for an email when your beach
> turns risky, or send a link to a friend.

**B — Limits and wrap-up (≈25 s)**
> It's a prediction, not a lab test, and we say that inside the app. Our data comes from
> one sample every two weeks, so storm days are under-represented, and we only cover 9
> beaches.
> Our next steps are more beaches, tide and wave data, and sharing the tool with Surfrider
> and lifeguards. Kai Check Oʻahu turns weather people already see into a swim decision
> they can actually use. Mahalo!

---

## Likely questions from a lay audience

**What exactly is enterococcus? Is it dangerous?**
It's a bacteria that lives in human and animal guts. It doesn't always make you sick by
itself, but when there's a lot of it, sewage or runoff is probably in the water, and that
can bring stomach bugs, skin rashes, and ear or eye infections.

**Why 130?**
130 per 100 mL is the Hawaiʻi Department of Health's limit for swimming water. We used the
same line the state uses.

**Doesn't the state already warn people?**
Yes, but the state tests most beaches only every week or two, and Brown Water Advisories
mostly follow big storms. Our test showed that a heavy-rain-only rule misses most unsafe
days. Our app gives an estimate for *every* day.

**How can you know without testing the water?**
We can't know for sure. We give a *probability*. The past shows a strong pattern: rain and
certain beaches go with high bacteria. The app applies that pattern to today's weather.

**How accurate is it?**
On 2025–26 samples it never saw, it flagged 80% of the unsafe days. The tradeoff is false
alarms: about one in three of its warnings turned out fine. For health, we'd rather warn
too often than miss.

**Why does a beach show caution when it's sunny today?**
Last week's rain still matters. Runoff and bacteria can stay in the water for a day or
more, and some beaches, like Kahaluʻu, are often high no matter the weather.

**Where does the data come from?**
Lab results from Surfrider Foundation's Blue Water Task Force volunteers, and weather from
Open-Meteo, a free weather service. The app downloads a fresh forecast every time it's
opened.

**Why only 9 beaches?**
Those are the popular swimming beaches with enough samples to learn from. We left out
stream mouths and boat ramps because people don't usually swim there, and they're dirty
almost all the time.

**Is it AI?**
It's machine learning. It learns a pattern from past data. It isn't a chatbot. We picked a
simple, explainable model on purpose, so we can show *why* it gives each number. We did use
AI coding assistants for help, and we disclosed that as the contest rules require.

**If the app says lower risk, is it 100% safe?**
No. Still avoid brown or murky water and places where streams or storm drains flow into
the ocean. The app says this too.

**Who is it for?**
Families, surfers, swimmers, tourists, and anyone heading to an Oʻahu beach. It's free and
works on a phone, with no account needed.

**What was the hardest part?**
**A:** Matching each lab sample with the weather from *before* it was taken, without
accidentally using future information. **B:** Turning a probability into something
non-experts understand at a glance.

**What's next?**
Adding more beaches, tide and wave data, and checking our predictions against new samples
as they come in. We also want to share the tool with Surfrider and local lifeguards.
