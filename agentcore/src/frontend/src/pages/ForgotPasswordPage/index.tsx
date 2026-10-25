import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  useRequestPasswordReset,
  useDirectPasswordReset,
} from "@/controllers/API/queries/auth";
import MothersonLogo from "@/assets/micore.svg";

type PageState = "form" | "email-sent" | "direct-form" | "success";

export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [state, setState] = useState<PageState>("form");
  const [error, setError] = useState("");

  const { mutate: requestReset } = useRequestPasswordReset();
  // ---- DIRECT RESET FALLBACK (remove when SMTP is ready on client) ----
  const { mutate: directReset } = useDirectPasswordReset();
  // ---- END DIRECT RESET FALLBACK ----

  function handleRequestReset(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    requestReset(email.trim().toLowerCase(), {
      onSuccess: (data: { method: string }) => {
        // ---- DIRECT RESET FALLBACK (remove when SMTP is ready on client) ----
        if (data.method === "direct") {
          setState("direct-form");
          return;
        }
        // ---- END DIRECT RESET FALLBACK ----
        setState("email-sent");
      },
      onError: () => setError(t("Something went wrong. Please try again.")),
    });
  }

  // ---- DIRECT RESET HANDLER (remove when SMTP is ready on client) ----
  function handleDirectReset(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError(t("Passwords do not match"));
      return;
    }
    if (newPassword.length < 8) {
      setError(t("Password must be at least 8 characters"));
      return;
    }
    directReset(
      { email: email.trim().toLowerCase(), new_password: newPassword },
      {
        onSuccess: () => setState("success"),
        onError: () =>
          setError(t("Failed to reset password. Check your email and try again.")),
      },
    );
  }
  // ---- END DIRECT RESET HANDLER ----

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 via-white to-gray-100 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <img src={MothersonLogo} alt="MiCore" className="h-16 w-auto" />
        </div>

        <div className="bg-white rounded-2xl shadow-xl border border-gray-200 p-8">

          {state === "form" && (
            <>
              <h2 className="text-2xl font-semibold text-gray-900 mb-2">
                {t("Reset Password")}
              </h2>
              <p className="text-sm text-gray-600 mb-6">
                {t("Enter your account email to receive a reset link.")}
              </p>
              <form onSubmit={handleRequestReset} className="space-y-4">
                <input
                  type="email"
                  required
                  placeholder={t("Email address")}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full h-11 px-4 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#da2128]/30"
                />
                {error && <p className="text-sm text-red-500">{error}</p>}
                <Button
                  type="submit"
                  className="w-full h-11 !bg-[#da2128] hover:!bg-[#b81c22] text-white rounded-lg font-medium text-sm"
                >
                  {t("Send Reset Link")}
                </Button>
              </form>
            </>
          )}

          {state === "email-sent" && (
            <div className="text-center">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                {t("Check your email")}
              </h2>
              <p className="text-sm text-gray-600">
                {t("If that email is registered, you'll receive a reset link shortly. It expires in 30 minutes.")}
              </p>
            </div>
          )}

          {/* ---- DIRECT RESET FALLBACK (remove when SMTP is ready on client) ---- */}
          {state === "direct-form" && (
            <>
              <h2 className="text-2xl font-semibold text-gray-900 mb-2">
                {t("Set New Password")}
              </h2>
              <p className="text-sm text-gray-600 mb-6">
                {t("Enter your new password below.")}
              </p>
              <form onSubmit={handleDirectReset} className="space-y-4">
                <input
                  type="password"
                  required
                  placeholder={t("New password")}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full h-11 px-4 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#da2128]/30"
                />
                <input
                  type="password"
                  required
                  placeholder={t("Confirm new password")}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full h-11 px-4 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#da2128]/30"
                />
                {error && <p className="text-sm text-red-500">{error}</p>}
                <Button
                  type="submit"
                  className="w-full h-11 !bg-[#da2128] hover:!bg-[#b81c22] text-white rounded-lg font-medium text-sm"
                >
                  {t("Set Password")}
                </Button>
              </form>
            </>
          )}
          {/* ---- END DIRECT RESET FALLBACK ---- */}

          {state === "success" && (
            <div className="text-center">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                {t("Password Updated")}
              </h2>
              <p className="text-sm text-gray-600 mb-6">
                {t("Your password has been set. You can now sign in.")}
              </p>
              <Button
                onClick={() => navigate("/login")}
                className="w-full h-11 !bg-[#da2128] hover:!bg-[#b81c22] text-white rounded-lg font-medium text-sm"
              >
                {t("Sign In")}
              </Button>
            </div>
          )}

          <div className="mt-6 text-center">
            <Link to="/login" className="text-sm text-gray-500 hover:text-gray-700">
              {t("← Back to Sign In")}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
