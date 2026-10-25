import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  useResetPasswordWithToken,
  useValidateResetToken,
} from "@/controllers/API/queries/auth";
import MothersonLogo from "@/assets/micore.svg";

export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [tokenStatus, setTokenStatus] = useState<
    "checking" | "valid" | "invalid"
  >("checking");

  const { mutate: resetPassword, isPending: isSubmitting } =
    useResetPasswordWithToken();
  const { mutate: validateToken } = useValidateResetToken();

  useEffect(() => {
    if (!token) {
      navigate("/forgot-password");
      return;
    }
    validateToken(
      { token },
      {
        onSuccess: () => setTokenStatus("valid"),
        onError: () => setTokenStatus("invalid"),
      },
    );
  }, [token, navigate, validateToken]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (isSubmitting) return;
    setError("");
    if (newPassword !== confirmPassword) {
      setError(t("Passwords do not match"));
      return;
    }
    if (newPassword.length < 8) {
      setError(t("Password must be at least 8 characters"));
      return;
    }
    resetPassword(
      { token, new_password: newPassword },
      {
        onSuccess: () => setSuccess(true),
        onError: (err: any) => {
          const detail =
            err?.response?.data?.detail || t("Invalid or expired reset link");
          setError(detail);
          // If the backend now considers the token unusable, flip to the
          // expired view so the user can't keep retrying.
          if (err?.response?.status === 400) {
            setTokenStatus("invalid");
          }
        },
      },
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 via-white to-gray-100 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <img src={MothersonLogo} alt="MiCore" className="h-16 w-auto" />
        </div>

        <div className="bg-white rounded-2xl shadow-xl border border-gray-200 p-8">
          {tokenStatus === "checking" ? (
            <div className="flex flex-col items-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
              <p className="mt-3 text-sm text-gray-500">
                {t("Verifying reset link...")}
              </p>
            </div>
          ) : tokenStatus === "invalid" ? (
            <div className="text-center">
              <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg
                  className="w-8 h-8 text-red-500"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
                  />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                {t("Reset link expired")}
              </h2>
              <p className="text-sm text-gray-600 mb-6">
                {t(
                  "This reset link is invalid or has already been used. Request a new one to continue.",
                )}
              </p>
              <Button
                onClick={() => navigate("/forgot-password")}
                className="w-full h-11 !bg-[#da2128] hover:!bg-[#b81c22] text-white rounded-lg font-medium text-sm"
              >
                {t("Request New Link")}
              </Button>
            </div>
          ) : !success ? (
            <>
              <h2 className="text-2xl font-semibold text-gray-900 mb-2">
                {t("Set New Password")}
              </h2>
              <p className="text-sm text-gray-600 mb-6">
                {t("Choose a new password for your account.")}
              </p>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="relative">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    required
                    autoComplete="new-password"
                    placeholder={t("New password")}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full h-11 pl-4 pr-11 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#da2128]/30"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword((v) => !v)}
                    aria-label={
                      showNewPassword
                        ? t("Hide password")
                        : t("Show password")
                    }
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showNewPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? "text" : "password"}
                    required
                    autoComplete="new-password"
                    placeholder={t("Confirm new password")}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full h-11 pl-4 pr-11 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#da2128]/30"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword((v) => !v)}
                    aria-label={
                      showConfirmPassword
                        ? t("Hide password")
                        : t("Show password")
                    }
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                {error && <p className="text-sm text-red-500">{error}</p>}
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="w-full h-11 !bg-[#da2128] hover:!bg-[#b81c22] disabled:!bg-[#da2128]/60 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm flex items-center justify-center gap-2"
                >
                  {isSubmitting && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  {isSubmitting ? t("Setting password...") : t("Set Password")}
                </Button>
              </form>
            </>
          ) : (
            <div className="text-center">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg
                  className="w-8 h-8 text-green-500"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
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
