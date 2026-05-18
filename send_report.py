import smtplib
import os
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import akshare as ak

def is_trade_day():
    try:
        today = datetime.now().strftime('%Y%m%d')
        trade_cal = ak.tool_trade_date_hist_sina()
        trade_dates = trade_cal['trade_date'].astype(str).str.replace('-', '').tolist()
        return today in trade_dates
    except Exception as e:
        print(f"⚠️ 交易日历获取失败: {e}，默认继续发送")
        return True

def send_email(report_text):
    user = os.environ['EMAIL_USER']
    password = os.environ['EMAIL_PASS']
    to = os.environ['EMAIL_TO']

    today = datetime.now().strftime('%Y-%m-%d')

    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = to
    msg['Subject'] = f'📡 DS波段扫描 {today}'

    # 简短正文
    body = f"DS波段扫描报告 {today}\n\n报告见附件，复制附件内容后粘贴给AI分析。"
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    # 附件
    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(report_text.encode('utf-8'))
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', f'attachment; filename="report_{today}.txt"')
    msg.attach(attachment)

    with smtplib.SMTP_SSL('smtp.126.com', 465) as server:
        server.login(user, password)
        server.send_message(msg)

    print("✅ 邮件发送成功")

if __name__ == '__main__':
    if not is_trade_day():
        print("📅 今日非交易日，跳过发送")
        sys.exit(0)

    with open('report.txt', 'r', encoding='utf-8') as f:
        report = f.read()

    send_email(report)
