import React from "react";
import ReactDOM from "react-dom/client";
import reportWebVitals from "./reportWebVitals";
import { I18nextProvider } from "react-i18next";
import i18n from "./i18n";

import "./style/classes.css";
// @ts-ignore
import "./style/index.css";
// @ts-ignore
import "./App.css";
import "./style/applies.css";

// @ts-ignore
import App from "./customization/custom-App";



/* ================= MSAL IMPORTS ================= */
import { PublicClientApplication, EventType, AuthenticationResult  } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { msalConfig } from "./authConfig";

/* ================================================ */

/**
 * MSAL instance should be created outside React tree.
 * MSAL Browser v4 requires initialize() before any interaction.
 */
const msalInstance = new PublicClientApplication(msalConfig);

// Listen for login success and set account
msalInstance.addEventCallback((event) => {
  if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
    const payload = event.payload as AuthenticationResult;
    if (payload.account) {
      msalInstance.setActiveAccount(payload.account);
    }
  }
});

/* ============== REACT ROOT ================= */

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

// Initialize MSAL, handle any pending redirects, then render
msalInstance
  .initialize()
  .then(() => msalInstance.handleRedirectPromise())
  .then(() => {
    // Set active account after initialization
    const accounts = msalInstance.getAllAccounts();
    if (!msalInstance.getActiveAccount() && accounts.length > 0) {
      msalInstance.setActiveAccount(accounts[0]);
    }

    root.render(
      <React.StrictMode>
        <I18nextProvider i18n={i18n}>
          <MsalProvider instance={msalInstance}>
            <App />
          </MsalProvider>
        </I18nextProvider>
      </React.StrictMode>
    );
  })
  .catch((err) => {
    console.error("[MSAL] Initialization failed:", err);
    // Render app without MSAL so the page isn't blank
    root.render(
      <React.StrictMode>
        <I18nextProvider i18n={i18n}>
          <App />
        </I18nextProvider>
      </React.StrictMode>
    );
  });

reportWebVitals();
