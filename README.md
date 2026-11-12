# Smile Check 🦷

A kid-friendly website that checks a tooth photo with AI and explains the results.
Runs on your own laptop with Python. Student science demo, not a medical device.

## 1. One-time setup

1. Install Python 3.10 or newer from python.org (tick "Add Python to PATH" on Windows).
2. Open a terminal in this `smile-check` folder and run:

   ```
   pip install -r requirements.txt
   ```

## 2. Connect Azure AI (optional, needs internet)

1. In the Azure portal, create an **Azure OpenAI** resource (or an AI Foundry project).
2. Deploy a vision model such as **gpt-4o** or **gpt-4o-mini**. Note the deployment name.
3. From the resource's "Keys and Endpoint" page, copy the endpoint and a key.
4. Copy `.env.example` to a new file named `.env` and fill it in.
5. Set a budget alert in Azure (Cost Management → Budgets), e.g. $10.

**Never put the key in your slides, code, or a photo of your screen.**

Without a `.env` file, the site runs in **Practice mode** and shows a clearly labelled
sample result. It also falls back to Practice mode automatically if the internet drops.

## 3. Start the website

```
python app.py
```

Open **http://localhost:5000** in Chrome or Edge.
The pill in the top-right corner says **AI connected** or **Practice mode**.

### Let visitors use their phones (optional)

Connect the laptop and phones to the same hotspot, then start with:

- Windows: `set SHARE_ON_NETWORK=1 && python app.py`
- Mac/Linux: `SHARE_ON_NETWORK=1 python app.py`

Find the laptop's IP (`ipconfig` on Windows, `ipconfig getifaddr en0` on Mac) and open
`http://<that-ip>:5000` on the phone. "Take a photo" opens the phone camera.
(Some browsers only allow the camera button on https; "Choose a photo" always works.)

## 4. Exhibit day checklist

- [ ] Laptop fully charged (HOSA provides no power or Wi-Fi)
- [ ] Ask your advisor if a phone hotspot is allowed
- [ ] Test with your big tooth model with painted brown spots
- [ ] Record a screen video of a full run as a backup
- [ ] Use model teeth or your own teeth only. Don't photograph classmates' mouths

## Files

| File | What it does |
|---|---|
| `app.py` | Python web server: cleans the photo, asks Azure GPT-4o, checks the answer, practice-mode fallback |
| `templates/index.html` | The kid-friendly page: Toothie mascot, stars, photo pins, tooth map, missions, read-aloud |
| `static/fonts/` | Fonts stored locally so the page looks right without internet |

## Privacy

Photos are processed in memory, location data is stripped, and nothing is saved on the laptop.
When AI is connected, the photo is sent to your own Azure OpenAI resource for analysis.

## Deploy to Azure Function App

Files used by Azure: `function_app.py` (wraps the Flask app), `host.json` (site opens at `/`, not `/api`),
`requirements.txt`, `.funcignore` (keeps `.env` and local files out of the upload).

1. Azure portal > Create a resource > **Function App** > **Flex Consumption**.
   Runtime **Python 3.13**, same region and resource group as your Azure OpenAI resource.
2. Function App > **Settings > Environment variables** > add:
   - `AZURE_OPENAI_ENDPOINT`
   - `AZURE_OPENAI_API_KEY`
   - `AZURE_OPENAI_DEPLOYMENT` (e.g. `gpt-4.1-mini`)
   - `AZURE_OPENAI_API_VERSION` (e.g. `2024-12-01-preview`)
   - `AzureWebJobsDisableHomepage` = `true`  (hides Azure's default start page at `/`)
   Click **Apply**.
3. VS Code > install the **Azure Functions** extension > sign in > open this folder >
   Ctrl+Shift+P > **Azure Functions: Deploy to Function App...** > pick your app.
   Azure installs the packages itself (remote build).
4. Open the **Default domain** from the Function App's Overview page.

Checks after deploying:
- `https://YOUR-APP/api/status` should show `"ai_ready": true` and `"key_set": true`.
- If `/` shows "Your Functions app is up and running", open `https://YOUR-APP/home` instead,
  and check that `AzureWebJobsDisableHomepage` is `true`.
- Errors: Function App > **Log stream** (look for "[Smile Check] Azure call failed").

Optional local test of the Azure version: install Azure Functions Core Tools,
copy `local.settings.json.example` to `local.settings.json`, fill it in, run `func start`.

## Deploy to Azure Container Apps (works on a Free Trial)

Uses `Dockerfile` (Python 3.13 + gunicorn on port 8000). Needs the Azure CLI:
https://learn.microsoft.com/cli/azure/install-azure-cli-windows

```
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az containerapp up --name smile-check --resource-group smile-check_group --location eastus --source . --ingress external --target-port 8000 --env-vars AZURE_OPENAI_ENDPOINT=https://YOUR-NAME.openai.azure.com/ AZURE_OPENAI_API_KEY=YOUR-KEY AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini AZURE_OPENAI_API_VERSION=2024-12-01-preview
```
The command prints the app's https link at the end. To update after code changes, run the same command again.
Check: `https://YOUR-LINK/api/status` should show `"ai_ready": true`.
