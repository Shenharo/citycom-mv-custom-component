"""Tests for reading the code from Citycom's email."""

import email
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from custom_components.citycom_mv_water_meter.imap import extract_code

# Body of a real "קוד אימות CityCom" email from citycom@gaon.com.
HTML = (
    '<div style="width:700px;padding:30px 20px">'
    '<h1 style="font-size:48px">קוד אימות CityCom</h1>'
    '<p style="font-size:24px">קוד האימות שלך הוא: <b>309968</b><br>'
    "הקוד תקף ל - 10 דקות. אם לא ביקשת קוד זה, התעלם מהודעה זו.</p>"
    "<p>נוצר על ידי City Com</p></div>"
)


def _parse(msg):
    return email.message_from_bytes(msg.as_bytes())


def test_html_email():
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header("קוד אימות CityCom", "utf-8").encode()
    msg["From"] = "CityCom <citycom@gaon.com>"
    msg.attach(MIMEText(HTML, "html", "utf-8"))
    assert extract_code(_parse(msg)) == "309968"


def test_plain_email():
    msg = MIMEText(
        "קוד האימות שלך הוא: 309968\nהקוד תקף ל - 10 דקות.", "plain", "utf-8"
    )
    assert extract_code(_parse(msg)) == "309968"


def test_english_wording():
    msg = MIMEText("Your verification code is: 4821. It expires in 10 minutes.")
    assert extract_code(_parse(msg)) == "4821"


def test_no_code():
    msg = MIMEText("שלום, החשבון שלך עודכן ב-27/10/2026.", "plain", "utf-8")
    assert extract_code(_parse(msg)) is None
