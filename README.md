# my-researcher

### A. Python Server
1. ```
   cd api
   copy config.json.sample config.json
   ```
3. In [`config.json`] fill in `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID` credentials from [Google Custom Search API](https://developers.google.com/custom-search/v1/overview).
4. Fill in `GROQ_API_KEY` credentials from .
5. Setup virtual environment, packages, and deploy the server
   ```
   virtualenv venv
   . venv/bin/activate
   pip install -r requirements.txt
   python app.py
   ```
   This is fine for dev testing.


### B. React Frontend
1. ```
   cd ui
   ```
2. Update `API_URL` in [`constants.js`](https://github.com/philfung/perplexed/blob/main//src/constants.js) to point to your server
3. ```
   npm install
   npm run build
   ```
3. In dev testing, to start the server:
   ```
   npm run start
   ```
   In production, to start the server:
   ```
   npm i -g npm@latest
   rm -rf node_modules
   rm -rf package-lock.json
   npm cache clean --force
   npm i --no-optional --omit=optional
   npm run build
   npm install -g serve
   server -s build
   ```
