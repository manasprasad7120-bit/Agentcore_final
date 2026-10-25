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
import {
  PublicClientApplication,
  EventType,
  type AuthenticationResult,
} from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { isSsoConfigured, msalConfig } from "./authConfig";

/* ================================================ */

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);

function renderApp(content: React.ReactNode) {
  root.render(
    <React.StrictMode>
      <I18nextProvider i18n={i18n}>{content}</I18nextProvider>
    </React.StrictMode>,
  );
}

if (!isSsoConfigured) {
  /**
   * Microsoft Entra SSO is not configured (AZURE_CLIENT_ID / AZURE_TENANT_ID
   * are empty). Skip MSAL entirely and run with local username/password
   * login — used for local demos and environments without Azure.
   */
  renderApp(<App />);
} else {
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

      renderApp(
        <MsalProvider instance={msalInstance}>
          <App />
        </MsalProvider>,
      );
    })
    .catch((err) => {
      console.error("[MSAL] Initialization failed:", err);
      // Render app without MSAL so the page isn't blank
      renderApp(<App />);
    });
}

reportWebVitals();
