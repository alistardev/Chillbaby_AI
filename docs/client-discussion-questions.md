# Chill Baby AI — a few things to align on

Before we finish the last pieces (settings, session setup, production deploy), it helps to talk through these. No need for long answers — rough direction is enough.

---

## Who’s using it and where?

- Is this mainly for **one nursery room**, **parents at home**, or both?
- Will **one person** monitor at a time, or do you need **several caregivers / rooms** on the same system?
- Do you already have a **URL or domain** for the live site, or will people connect by **IP address** for now?

---

## Each meal session — what do we ask upfront?

- When someone starts monitoring, should they always pick **which child**? (We have that today.)
- Do you also want **room / camera name** (e.g. “Room 2”, “Kitchen”) saved with each meal?
- Any need to note **temperature** manually for now, or skip until the T40 device is hooked up?

---

## Food and allergies

- Is the current setup OK — **pick allergens at login**, plus **add custom ones** (like “banana”) on the child page?
- For the **demo / launch**, are there **must-detect foods** we should test with you, or is “good enough on common foods” fine until the model is retrained?
- Do caregivers care about **how much was eaten**, or mainly **what food was on the plate** and **allergy warnings**?

---

## Alerts

- Are **on-screen alerts** enough (red banner, sound in the room), or do you want **text/email** to someone not watching the screen?
- How noisy are the rooms? Should we **tune cough detection** with you on a real session?
- Is **“child not in frame”** something you want always on, or optional?

---

## Dashboard and records

- Is the **dashboard as it is** enough for staff review, or do you need **export** (spreadsheet/PDF) for parents or regulators?
- How long should **meal and allergen history** be kept — weeks, a year, until the child leaves?

---

## Privacy and hosting

- Any rules on **where data lives** (UK/EU only, etc.) or **using cloud APIs** (Clarifai, Azure for nutrition)?
- Are you OK with **labels and logs only**, or do you want **saved photos/video** from meals later?

---

## Hardware and performance

- What cameras are realistic — **laptop webcam**, **ManyCam**, fixed **T40**, mix?
- The **Ubuntu server has no GPU** — a few seconds’ delay on food/emotion is normal there. Is that acceptable for staff, or do we need a faster machine?

---

## Launch

- What’s the **target date** and **who’s in the room** for the first real demo (staff pilot vs investor)?
- What’s **in** for v1 vs **nice to have later** (settings page, meal summary at end, quantity tracking, etc.)?
- Who handles **API costs** (Clarifai, Azure) and is there a rough **monthly budget**?

---

*After this chat we can lock scope for: device/location picker, settings page, dashboard filters, end-of-meal summary, and production setup (HTTPS, login if needed).*
