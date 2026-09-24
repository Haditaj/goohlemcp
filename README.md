# goohle-mcp

یک سرور MCP برای وصل کردن **Claude Code** (یا Claude Desktop) به
**Google Analytics 4**، **Google Search Console** و **Google Tag Manager**.
Claude با این سرور داده‌ها رو می‌خونه و تحلیل می‌کنه. اگه اجازه بدید، تغییر هم ایجاد می‌کنه:
ساخت Custom Dimension و Key Event، ثبت Sitemap، ساخت و ویرایش تگ و تریگر در GTM و انتشار ورژن.

> همه‌چیز روی سیستم خودتون اجرا می‌شه (stdio). توکن گوگل فقط روی دیسک خودتون ذخیره می‌شه و هیچ سرویس واسطی وجود نداره.

---

## چرا یه پروژه‌ی جدید؟

| پروژه | GA4 | Search Console | GTM | تغییر دادن |
|---|---|---|---|---|
| [googleanalytics/google-analytics-mcp](https://github.com/googleanalytics/google-analytics-mcp) (رسمی گوگل) | ✅ گزارش‌ها | ❌ | ❌ | ❌ فقط خواندنی (`analytics.readonly`) |
| [ZubeidHendricks/youtube-mcp-server](https://github.com/ZubeidHendricks/youtube-mcp-server) | ❌ | ❌ | ❌ | فقط داده‌های عمومی یوتیوب (ویدیو، کانال، زیرنویس)؛ به این نیاز ربطی نداره |
| [stape-io/google-tag-manager-mcp-server](https://github.com/stape-io/google-tag-manager-mcp-server) | ❌ | ❌ | ✅ | ✅ (نسخه‌ی hosted، OAuth از طریق سرور Stape) |
| [AminForou/mcp-gsc](https://github.com/AminForou/mcp-gsc) | ❌ | ✅ | ❌ | فقط Sitemap |
| **goohle-mcp (همین ریپو)** | ✅ گزارش + تنظیمات | ✅ | ✅ | ✅ با سه سطح دسترسی، dry-run و لاگ |

پروژه‌های بالا هر کدوم فقط یکی از این سه سرویس رو پوشش می‌دن. یعنی سه نصب جدا، سه بار لاگین و سه مدل امنیتی متفاوت.
این پروژه هر سه رو با **یک لاگین** در یک سرور جمع کرده. تغییرات هم فقط وقتی انجام می‌شن که خودتون صریحاً اجازه بدید.

---

## ابزارها (۴۹ ابزار)

### Google Analytics 4 (`ga4_*`)
**خواندن:** `ga4_list_accounts` · `ga4_get_property` · `ga4_list_data_streams` · `ga4_get_metadata` ·
`ga4_run_report` · `ga4_run_realtime_report` · `ga4_list_custom_definitions` · `ga4_list_key_events` ·
`ga4_get_data_retention` · `ga4_list_annotations` · `ga4_search_change_history`

**تغییر:** `ga4_create_property` · `ga4_create_web_stream` · `ga4_create_custom_dimension` · `ga4_update_custom_dimension` · `ga4_archive_custom_dimension` ·
`ga4_create_custom_metric` · `ga4_archive_custom_metric` · `ga4_create_key_event` · `ga4_delete_key_event` ·
`ga4_update_data_retention` · `ga4_update_property` · `ga4_create_annotation`

### Search Console (`gsc_*`)
**خواندن:** `gsc_list_sites` · `gsc_search_analytics` (کلیک، ایمپرشن، CTR، پوزیشن) · `gsc_inspect_url` (وضعیت ایندکس) · `gsc_list_sitemaps`

**تغییر:** `gsc_submit_sitemap` · `gsc_delete_sitemap`

### Tag Manager (`gtm_*`)
**خواندن:** `gtm_list_accounts` · `gtm_list_containers` · `gtm_list_workspaces` · `gtm_list_entities` (تگ، تریگر، متغیر، فولدر، تمپلیت، …) ·
`gtm_get_entity` · `gtm_list_built_in_variables` · `gtm_get_workspace_status` · `gtm_quick_preview` · `gtm_list_versions` · `gtm_get_version` · `gtm_get_install_snippet`

**تغییر:** `gtm_create_container` · `gtm_create_workspace` · `gtm_create_entity` · `gtm_update_entity` · `gtm_delete_entity` · `gtm_revert_entity` ·
`gtm_set_built_in_variables` · `gtm_create_version` · `gtm_publish_version`

### پرامپت‌های آماده (در Claude Code به شکل اسلش‌کامند)
- `/mcp__goohle__tracking_audit`: بررسی کامل GA4 و GTM (Measurement ID، تگ‌های بدون تریگر، Key Eventهای بدون داده، پارامترهای ثبت‌نشده، …)
- `/mcp__goohle__seo_review`: تحلیل Search Console: برنده‌ها و بازنده‌ها، فرصت‌های سریع (پوزیشن ۵ تا ۱۵)، مشکلات Sitemap و ایندکس
- `/mcp__goohle__weekly_report`: گزارش هفتگی از GA4 و Search Console

---

## امنیت: سه سطح دسترسی

سطح دسترسی با متغیر `GOOHLE_MCP_MODE` تعیین می‌شه:

| مقدار | چه کاری مجازه |
|---|---|
| `read` (پیش‌فرض) | فقط خواندن. ابزارهای تغییر فقط با `dry_run=true` کار می‌کنن و درخواست رو نشون می‌دن بدون اینکه چیزی رو عوض کنن |
| `write` | ساخت و ویرایش در GA4، Sitemap در GSC، تغییر Workspace و ساخت Version در GTM |
| `publish` | همه‌ی موارد بالا به‌علاوه‌ی **انتشار زنده‌ی GTM** (`gtm_publish_version`) |

محافظ‌های دیگه:
- **dry_run**: همه‌ی ابزارهای تغییر پارامتر `dry_run` دارن. با این پارامتر، دقیقاً همون درخواستی که قراره به گوگل بره (متد، آدرس و بدنه) برگردونده می‌شه و چیزی تغییر نمی‌کنه.
- **لاگ تغییرات**: هر تغییر، چه موفق، چه ناموفق و چه dry-run، در فایل `~/.config/goohle-mcp/audit.jsonl` ثبت می‌شه.
- **Fingerprint در GTM**: ویرایش تگ‌ها با fingerprint انجام می‌شه. اگه کس دیگه‌ای همزمان همون تگ رو عوض کرده باشه، تغییر رد می‌شه و روی کارش نوشته نمی‌شه.
- **تأیید Claude Code**: Claude Code برای هر ابزار MCP از شما اجازه می‌گیره. ابزارهای خواندنی رو می‌تونید با «Yes, don't ask again» دائمی کنید و ابزارهای تغییر رو روی «هر بار بپرس» نگه دارید.
- تغییرات GTM اول فقط در Workspace اعمال می‌شن. تا وقتی Version ساخته و Publish نشه، روی سایت اثری ندارن.

---

## راه‌اندازی (حدود ۱۰ دقیقه)

### ۱) پروژه در Google Cloud

1. به [console.cloud.google.com](https://console.cloud.google.com) برید و یک پروژه بسازید (یا پروژه‌ی موجود رو انتخاب کنید).
2. در **APIs & Services → Library** این چهار API رو فعال کنید:
   - Google Analytics Admin API
   - Google Analytics Data API
   - Google Search Console API
   - Tag Manager API
3. در **Google Auth Platform → Branding / Audience** صفحه‌ی OAuth consent رو بسازید.
   نوع External رو انتخاب کنید و ایمیل خودتون رو در **Test users** اضافه کنید.
   > توجه: وقتی اپ در حالت *Testing* باشه، توکن هر ۷ روز منقضی می‌شه. برای استفاده‌ی طولانی‌مدت یا اپ رو **Publish** کنید (برای استفاده‌ی شخصی نیازی به بررسی گوگل نیست، فقط یه صفحه‌ی هشدار «unverified» یک بار نشون داده می‌شه)، یا هر هفته `goohle-mcp auth` رو دوباره اجرا کنید.
4. در **Clients → Create client** نوع **Desktop app** رو انتخاب کنید و فایل JSON رو دانلود کنید (مثلاً در `~/client_secret.json`).

### ۲) نصب

به [uv](https://docs.astral.sh/uv/getting-started/installation/) نیاز دارید:

**راه سریع (macOS و Linux):** این اسکریپت مراحل ۲ تا ۴ رو یک‌جا انجام می‌ده:

```bash
curl -LsSfO https://raw.githubusercontent.com/haditaj/goohlemcp/claude/vibrant-knuth-ovrixn/scripts/install.sh
bash install.sh ~/Downloads/client_secret.json write
```

**نصب دستی:**

```bash
uv tool install "git+https://github.com/haditaj/goohlemcp@claude/vibrant-knuth-ovrixn"
```

> بعد از merge شدن در `main`، بخش `@claude/vibrant-knuth-ovrixn` رو می‌تونید حذف کنید.

### ۳) لاگین با گوگل (فقط یک بار)

```bash
goohle-mcp auth --client-secrets ~/client_secret.json
```

مرورگر باز می‌شه. با اکانتی لاگین کنید که به GA4، Search Console و GTM دسترسی داره.
اگه فقط خواندن لازم دارید، `--read-only` رو اضافه کنید.

برای بررسی وضعیت:

```bash
goohle-mcp status
```

### ۴) اضافه کردن به Claude Code

```bash
# فقط خواندن (پیشنهاد برای شروع)
claude mcp add goohle --scope user -- goohle-mcp

# خواندن و تغییر (بدون انتشار زنده‌ی GTM)
claude mcp add goohle --scope user -e GOOHLE_MCP_MODE=write -- goohle-mcp

# با اجازه‌ی انتشار GTM
claude mcp add goohle --scope user -e GOOHLE_MCP_MODE=publish -- goohle-mcp
```

برای عوض کردن سطح دسترسی، اول `claude mcp remove goohle` و بعد دوباره `add` کنید.
داخل Claude Code با `/mcp` می‌تونید وضعیت سرور رو ببینید.

### Claude Desktop

فایل `claude_desktop_config.json` رو باز کنید (macOS: `~/Library/Application Support/Claude/`، Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "goohle": {
      "command": "goohle-mcp",
      "env": { "GOOHLE_MCP_MODE": "write" }
    }
  }
}
```

> اگه Claude Desktop دستور `goohle-mcp` رو پیدا نکرد، مسیر کاملش رو بدید (خروجی `which goohle-mcp`).

### جایگزین: Service Account (برای اتوماسیون یا سرور)

یک Service Account بسازید، کلید JSON اون رو دانلود کنید و ایمیلش رو در هر سه محصول به‌عنوان کاربر اضافه کنید:
در GA4 نقش Editor، در Search Console نقش Owner یا Full و در GTM دسترسی Publish. بعد به جای مرحله‌ی ۳:

```bash
claude mcp add goohle --scope user \
  -e GOOHLE_MCP_SERVICE_ACCOUNT_FILE=/path/to/key.json \
  -e GOOHLE_MCP_MODE=write -- goohle-mcp
```

---

## چند نمونه درخواست

```
حساب‌ها و پراپرتی‌های GA4 من رو لیست کن.

ترافیک ۲۸ روز اخیر رو به تفکیک کانال با ۲۸ روز قبلش مقایسه کن و بگو کدوم کانال افت کرده.

توی Search Console، کوئری‌هایی که پوزیشن ۵ تا ۱۵ و ایمپرشن بالا دارن رو پیدا کن و برای هر صفحه پیشنهاد عنوان بده.

وضعیت ایندکس https://example.com/blog/x رو چک کن.

توی GTM یه تگ GA4 برای رویداد generate_lead بساز که روی form_submit فایر بشه. اول dry_run نشون بده.

پارامتر article_author رو به‌عنوان Custom Dimension ثبت کن.

همه‌ی تغییرات Workspace فعلی GTM رو بهم نشون بده، quick preview بگیر و اگه خطا نداشت یه Version بساز. (Publish رو خودم تأیید می‌کنم.)
```

---

## محدودیت‌ها و نکته‌ها

- **Request Indexing** در Search Console از طریق API ممکن نیست (Indexing API گوگل فقط برای JobPosting و BroadcastEvent کار می‌کنه). Claude وضعیت ایندکس رو بررسی می‌کنه ولی درخواست ایندکس باید دستی انجام بشه.
- `gtm_create_version` مثل رابط کاربری GTM، Workspace فعلی رو مصرف می‌کنه و یک Workspace جدید برمی‌گردونه.
- برای برگشت به قبل در GTM، ورژن قبلی رو از `gtm_list_versions` پیدا کنید و دوباره Publish کنید.
- `ga4_search_change_history` و `gtm_quick_preview` حتی برای خواندن هم به لاگین کامل (بدون `--read-only`) نیاز دارن.
- ID پراپرتی GA4 عدده (مثلاً `123456789`) و با Measurement ID (`G-XXXX`) فرق داره.

## عیب‌یابی

| خطا | راه‌حل |
|---|---|
| `No Google credentials found` | `goohle-mcp auth --client-secrets …` رو اجرا کنید |
| `… API is not enabled` | اون API رو در پروژه‌ی Google Cloud فعال کنید و یک دقیقه صبر کنید |
| `insufficient authentication scopes` | دوباره `goohle-mcp auth` رو **بدون** `--read-only` اجرا کنید |
| `… runs in 'read' mode` | `GOOHLE_MCP_MODE=write` (یا `publish`) رو در تنظیمات MCP بذارید |
| `invalid_grant` بعد از یک هفته | اپ OAuth در حالت Testing هست؛ Publish کنید یا دوباره لاگین کنید |

## تنظیمات

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `GOOHLE_MCP_MODE` | `read` | `read` / `write` / `publish` |
| `GOOHLE_MCP_CONFIG_DIR` | `~/.config/goohle-mcp` | محل توکن و لاگ |
| `GOOHLE_MCP_TOKEN_FILE` | `<config>/token.json` | مسیر توکن OAuth |
| `GOOHLE_MCP_SERVICE_ACCOUNT_FILE` | - | کلید Service Account (به جای OAuth) |
| `GOOHLE_MCP_AUDIT_LOG` | `<config>/audit.jsonl` | لاگ تغییرات |

اگه هیچ‌کدوم از این دو (توکن یا Service Account) نباشه، از
[Application Default Credentials](https://cloud.google.com/docs/authentication/provide-credentials-adc) استفاده می‌شه.

## توسعه

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
```

تست‌ها با discovery documentهای واقعی گوگل و یک HTTP جعلی اجرا می‌شن و به اکانت گوگل نیازی ندارن.
