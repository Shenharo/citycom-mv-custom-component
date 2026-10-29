# Citycom MV Water Meter Home Assistant Integration

This custom component integrates your Citycom MV water meters with Home Assistant. It discovers every meter on your account and creates a device with sensors for each one.

## Sensors

For each meter:

| Sensor | Description |
| --- | --- |
| Meter reading | Total meter reading in m³. Can be added to the Energy dashboard as a water source. |
| Consumption this month | Water used since the start of the month, in m³. |
| Last reading time | When the meter last reported. |
| Consumption yesterday | Total water used the previous day, in m³. |
| Consumption last 7 days | Total water used over the 7 full days before today, in m³. |
| Cost this month (estimate) | Only when prices are set (see below). In your Home Assistant currency. |
| Projected consumption this month / Budget used | Only when a monthly budget (m³) is set under Configure. |
| Projected cost this month | Only when prices are set. |
| Possible leak (binary) | Only when a leak threshold is set. On when the average flow between two night readings (both between 22:00 and 07:00, at least 2 hours apart) is above the threshold in litres per hour. Meters report every few hours, so this is a coarse check. |
| Alert (event) | Fires `alert` or `alert_cleared` when a Citycom alert appears or clears. Alerts that exist at startup are not reported. |
| Login expires (diagnostic) | When the current Citycom login expires, on a separate "Citycom account" device. |
| Alert (binary) | On while Citycom reports an active alert (leak, abnormal flow...). The `alerts` attribute lists them. |
| Not reporting (binary, diagnostic) | On when the meter has not reported for 24 hours. |

The last 35 days of daily consumption are also imported as long-term statistics (`citycom_mv_water_meter:meter_<id>_consumption`), refreshed every 3 hours. Add them to the Energy dashboard to see past usage per day.

### Cost estimate

Citycom does not show prices to residents, so the cost sensor is calculated from prices you enter with the **Configure** button (copy them from your water bill):

- **Regular price per m³** (required to create the sensor).
- **Over-usage price per m³** (defaults to the regular price), **drain price per m³** and a **fixed monthly fee** (all optional).
- **Monthly allowance per person (m³)**: water up to the allowance times the number of people is charged at the regular price, the rest at the over-usage price. The number of people comes from your Citycom account unless you enter it.

It is an estimate of this month's consumption so far; bills may differ (for example because of billing periods or taxes).

Use **Download diagnostics** on the integration page when reporting a problem; passwords and tokens are redacted.

Data is polled every 30 minutes by default. Polling only reads data and sends no email; change the interval with the integration's **Configure** button.

## How login works

Citycom requires a verification code (2FA) on every login, and a login lasts 10 hours with no way to renew it. To keep working on its own, the integration asks Citycom to send the code by **email** and reads it from your mailbox over **IMAP**. It logs in again automatically about 45 minutes before each token expires.

You need:

- Your Citycom username and password (the ones you use on https://citycom-mv.com/login).
- IMAP access to the mailbox the codes are sent to. For Gmail:
  1. Turn on 2-Step Verification for the Google account.
  2. Create an App Password at https://myaccount.google.com/apppasswords and use it as the IMAP password. Your regular Gmail password will not work.

The codes come from `citycom@gaon.com`. If you use a filter that moves them out of the inbox, set the mail folder accordingly (for example `[Gmail]/All Mail`).

## Installation

### HACS (Recommended)

1. Go to **HACS > Integrations** in your Home Assistant UI.
2. Click the three dots (menu) in the top right and select **Custom repositories**.
3. Add `https://github.com/Shenharo/citycom-mv-custom-component` and select "Integration" as the category.
4. Find "Citycom MV water meter" in the HACS integrations list and click "Install".
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/citycom_mv_water_meter` folder to your Home Assistant `custom_components` directory:

   ```
   <config>/custom_components/citycom_mv_water_meter/
   ```

3. Restart Home Assistant.

## Configuration

1. Go to **Settings > Devices & Services > Add Integration** and search for "Citycom MV water meter".
2. Enter your Citycom username and password, the email address the codes are sent to, and its IMAP app password.
3. The integration logs in and waits up to 2 minutes for the code email. If it does not arrive, you can type the code yourself.

### Avoiding notifications for code emails

A code email arrives about every 9 hours. To keep them out of your inbox, create a Gmail filter for `from:citycom@gaon.com` with **Skip the Inbox** and **Mark as read**, then set the mail folder to `[Gmail]/All Mail` with the **Configure** button.

If Citycom or the mail server later rejects a password, Home Assistant shows a re-authentication notice where you can enter the new ones.

Requires Home Assistant 2025.8 or newer.
