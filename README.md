# Citycom MV Water Meter Home Assistant Integration

This custom component integrates your Citycom MV water meters with Home Assistant. It discovers every meter on your account and creates a device with sensors for each one.

## Sensors

For each meter:

| Sensor | Description |
| --- | --- |
| Meter reading | Total meter reading in m³. Can be added to the Energy dashboard as a water source. |
| Consumption this month | Water used since the start of the month, in m³. |
| Last reading time | When the meter last reported. |

Data is polled every 30 minutes.

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

If Citycom or the mail server later rejects a password, Home Assistant shows a re-authentication notice where you can enter the new ones.

Requires Home Assistant 2025.6 or newer.
