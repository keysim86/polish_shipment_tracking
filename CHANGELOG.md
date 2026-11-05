# Changelog

Changes in this fork of [stirante/polish_shipment_tracking](https://github.com/stirante/polish_shipment_tracking). Versions from 1.5.4 onwards are this fork's own and do not match upstream version numbers.

The same notes are published with each [GitHub release](https://github.com/radzio/polish_shipment_tracking/releases), which is where HACS reads them from.

## Unreleased (keysim86 fork)

Security and reliability fixes from a code review of 1.11.1.

- **Card: parcel data can no longer inject HTML.** The shipment card put sender names, event descriptions, locations and pickup codes into the page without escaping, so a sender name chosen by whoever ships a parcel could run script in the browser of anyone viewing the card. Every value is now escaped, and links and images accept only https (tel: for phone numbers). Logos set in the card config (`courier_logos`) may also be http, `data:image/…` or a Home Assistant path such as `/local/…`.
- **Card: the QR code is now opt-in.** The QR image is rendered by an external service (quickchart.io), which received the locker QR payload or pickup code in its URL. It is shown only with `show_dialog_qr_code: true`. Cards saved through the editor before this change may already contain `show_dialog_qr_code: true` — switch it off there if you don't want it.
- **Pickup secrets stay out of the recorder.** Open codes, PINs, pickup and QR codes, phone numbers, recipient and receiver names, the raw courier payload, scan history, package lists and the ignore list are no longer written to the database. They stay in the live state that cards and dashboards read. Rows written before the update stay until the recorder purges them.
- **Logs no longer contain identifiers or full server responses.** Errors keep the HTTP status, the OAuth error and a short masked snippet; URLs are logged by host only (ORLEN puts the phone number and device id in the path). The DPD management link is no longer logged.
- **InPost and DPD: renewed tokens are saved even when a poll fails.** DPD renews its short-lived token on almost every poll but saved it only after a 401, so after a restart the integration fell back to the sign-in refresh token and eventually asked for a new SMS sign-in. InPost replaces its refresh token on every refresh but saved it only after a successful poll. Renewed tokens are now saved after every poll and after the DPD management button, never over tokens a re-authentication has just written. The DPD refresh is single-flight and times out after 30 s.
- **Services validate tracking numbers** (4–64 ASCII letters or digits, no control characters), and the ignore list is capped at 100 entries: the oldest entries that no account returns go first. Ignored numbers are stored and shown normalised (upper case, without separators).
- **Buttons are no longer removed and re-created on every update** (the sensor clean-up was deleting the integration's own buttons).
- **Pocztex: the cash-on-delivery row no longer shows "undefined zł"** when the parcel has no amount.
- The static path now serves only the card file instead of the whole `frontend` package directory.

## 1.11.1 – 2026-11-04

- **ORLEN Paczka: “ready for pickup” parcels no longer show as “unknown”.** When an ORLEN parcel reached its pick-up point or locker, its status could show as *unknown* instead of *waiting for pickup*, because ORLEN uses point/locker-specific status codes (the `*_pudo` family) that were not all in the lookup table. ORLEN now falls back to the parcel’s own Polish status description whenever the status code is not recognised, so *ready for pickup* — and the other point/locker states — are classified correctly. Also maps “not collected / expired” parcels (previously left as *unknown*) to *returned*.

## 1.11.0 – 2026-10-31

- **Expired logins now tell you.** When a courier's saved sign-in stops working (an expired or revoked token, a disabled account, an expired cookie), the account used to just go quiet — its parcels stopped updating with no warning. Home Assistant now shows a **"Reconfigure / Reauthenticate" notification and button** for the affected account, like it already did for InPost. Previously only InPost did this; every other courier failed silently.
- **Reconnect in place — no more delete and re-add.** The Reauthenticate button re-runs that courier's own sign-in and updates the existing account, keeping its history and sensors:
  - **DPD, DHL, ORLEN** – a new code is sent to the account's phone; you just enter it.
  - **Pocztex, GLS** – re-enter the password.
  - **Allegro, UPS** – paste a fresh cookie / "Copy as cURL".
  - **InPost** – unchanged (browser sign-in).
- Re-authentication refuses a different account than the one being renewed, where the account identity is known (phone / e-mail), so one account can't overwrite another.
- Note: for the cookie-based couriers (DHL cookie logins, GLS, Allegro, UPS) an expired cookie does not always report a clean error, so the notification can occasionally lag; the token-based couriers (DPD, ORLEN, Pocztex, InPost, DHL SMS) are detected reliably.

## 1.10.1 – 2026-10-30

- **DHL: no more duplicated parcels across household accounts.** When the same DHL parcel appeared in more than one of your DHL accounts (e.g. a household where DHL shows one person's parcel to both), it created a sensor under each account. It now shows once, under the actual recipient (taken from the parcel's recipient phone in the DHL details). A parcel is only hidden from the other account while that recipient account is also currently showing it, so it can never disappear from both.

## 1.10.0 – 2026-10-14

- **New carrier: ORLEN Paczka (account-based).** Signs in with a phone number + SMS code, like InPost/DPD, and lists your incoming ORLEN Paczka parcels with status, pickup point, collection PIN and sender. Only received parcels are shown (ones you send are filtered out). Reverse-engineered from the ORLEN Paczka app's own API.

## 1.9.3 – 2026-10-14

- **InPost: new sign-in.** InPost turned off the SMS-code login and its old token-refresh endpoint, so every InPost account failed with "InPost API Error: 404". InPost accounts now sign in on the InPost website (OAuth): the setup shows a link, you sign in in your browser and paste the address the sign-in ends on. Ported from upstream ([stirante#18](https://github.com/stirante/polish_shipment_tracking/issues/18)).
- Existing InPost accounts have to sign in again once: Home Assistant asks for it with a re-authentication notification and keeps the existing sensors.
- Renewed InPost tokens are saved straight away, so a restart does not force another sign-in.
- Re-authentication refuses a sign-in to a different InPost account than the one being renewed.

## 1.9.2 – 2026-10-08

- **Allegro Business: pickup code, phone and QR code.** They are now read from version 2 of Allegro's packages feed, which covers business orders too. Previously only private-account orders had them.
- Allegro Business packages also get the pickup point name, so `delivery_type` is recognised for them.

## 1.9.1 – 2026-10-07

- **InPost: redirected parcels stay visible.** InPost removes a courier parcel from the account's list once it is redirected to another address, so it used to disappear from Home Assistant while still on its way. A parcel that leaves the list before delivery is now fetched by its number until it is delivered.
- New action `polish_shipment_tracking.track_shipment`: track an InPost shipment by number when the account's list does not return it.

## 1.9.0 – 2026-10-07

- **Delivery type.** Every shipment sensor has a `delivery_type` attribute saying where the shipment is going: `home`, `parcel_locker`, `pickup_point`, or `unknown` when the carrier's data does not say. The values are the same for every carrier.
- The card shows the delivery type in the list and in the shipment details; both can be switched off in the card editor.
- Allegro: new `delivery_method` (for example "Allegro Automat ORLEN Paczka") and `pickup_point_name` attributes.
- Coverage: InPost, DPD (courier delivery), DHL (courier delivery), GLS and Allegro are recognised. DPD and DHL locker/point deliveries are recognised on a best-effort basis, and Pocztex and UPS mostly report `unknown` for now, because no such shipment has been observed yet.

## 1.8.2 – 2026-10-06

- Allegro: a package waiting to be handed to the carrier (status `PENDING`, "Przesyłka oczekuje na nadanie") is shown as "created" instead of "unknown".

## 1.8.1 – 2026-10-05

- **Ignore list cleans itself up.** An ignored shipment is removed from the list 24 hours after the account that used to return it stops returning it. If another account still returns it, it stays ignored. Entries no account can vouch for are still dropped after 30 days.

## 1.8.0 – 2026-10-05

- **Ignore shipments.** A shipment that will never arrive (for example a label the sender replaced) can be hidden, for every carrier:
  - from the card: the crossed-out eye icon in the shipment details, clicked twice;
  - with the `polish_shipment_tracking.ignore_shipment` action.
- `polish_shipment_tracking.unignore_shipment` brings a shipment back.
- The ignored shipments are listed in the `ignored_shipments` attribute of the "Active shipments" sensor.
- README: all supported carriers with their login method, and how multiple accounts per carrier behave.
- Manifest and README links point at this fork.

## 1.7.1 – 2026-09-14

- DPD: the `HANDED_OVER_FOR_DELIVERY_PUDO` status is recognised as "handed out for delivery" instead of "unknown".
- Pocztex: shipments the app has archived are treated as finished, so their sensors are removed.

## 1.7.0 – 2026-07-27

- **New carrier: UPS.** Set up by pasting a "Copy as cURL" of the `GetIncomingShipments` request from the ups.com dashboard; the session is kept alive by polling.

## 1.6.4 – 2026-07-25

- Allegro: a package that its real carrier starts tracking is dropped from Allegro within seconds, instead of showing twice until Allegro's next refresh.

## 1.6.3 – 2026-07-24

- Allegro: the seller (shop name) is shown as the sender.

## 1.6.2 – 2026-07-24

- Allegro: accounts are labelled "Private" / "Business" instead of "(None)".

## 1.6.1 – 2026-07-24

- Allegro: pickup code and QR code for packages waiting for pickup, and the real carrier's icon on each row.
- DHL: the Altcha captcha solver needed for logging in is back.

## 1.6.0 – 2026-07-24

- **New carrier: Allegro.** Uses the `QXLSESSID` session cookie, for private and business accounts. A package already tracked through its real carrier's account is not shown twice.

## 1.5.4 – 2026-07-08

First release of this fork, based on upstream 1.5.0.

- Multiple accounts of the same carrier no longer collide: entities are scoped per account, and DHL and GLS accounts each get their own isolated session.
- InPost: a parcel shared between your own accounts is shown once, under its owner.
- DHL: sender and timeline details, and all active shipments are fetched (the list is paginated).
- DPD: the sender falls back to the company name when the sender's name is empty.
