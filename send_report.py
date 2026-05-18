import smtplib
import os
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import akshare as ak

def is_trade_day():
    """检查今天是否是A股交易日"""
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

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, sans-serif; padding: 16px; background: #f5f5f5; }}
  .container {{ background: white; border-radius: 12px; padding: 20px; max-width: 600px; margin: 0 auto; }}
  h2 {{ color: #333; font-size: 18px; }}
  .report-box {{ background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 8px; 
                 font-family: monospace; font-size: 12px; white-space: pre-wrap; 
                 word-break: break-all; overflow-x: auto; }}
  .copy-btn {{ display: block; width: 100%; padding: 12px; margin-top: 12px;
               background: #007AFF; color: white; border: none; border-radius: 8px;
               font-size: 16px; cursor: pointer; text-align: center; }}
  .copy-btn:active {{ background: #0056CC; }}
  .tip {{ color: #888; font-size: 12px; margin-top: 8px; text-align: center; }}
</style>
</head>
<body>
<div class="container">
  <h2>📡 DS波段扫描报告 {today}</h2>
  <div class="report-box" id="report">{report_text}</div>
  <button class="copy-btn" onclick="copyReport()">📋 一键复制报告</button>
  <p class="tip">复制后直接粘贴给 DeepSeek / Claude 分析</p>
</div>
<script>
function copyReport() {{
  const text = document.getElementById('report').innerText;
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(text).then(() => {{
      const btn = document.querySelector('.copy-btn');
      btn.textContent = '✅ 已复制！';
      setTimeout(() => btn.textContent = '📋 一键复制报告', 2000);
    }});
  }} else {{
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    const btn = document.querySelector('.copy-btn');
    btn.textContent = '✅ 已复制！';
    setTimeout(() => btn.textContent = '📋 一键复制报告', 2000);
  }}
}}
</script>
</body>
</html>
"""

    msg = MIMEMultipart('alternative')
    msg['From'] = user
    msg['To'] = to
    msg['Subject'] = f'📡 DS波段扫描 {today}'

    msg.attach(MIMEText(html, 'html', 'utf-8'))

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
