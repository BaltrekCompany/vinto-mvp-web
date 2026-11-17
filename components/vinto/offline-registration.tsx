"use client";

import { useEffect } from "react";

// OFF-02 registers only a PUBLIC shell. Existing central screens and auth flows remain unchanged.
// No app data is cached, and this does not grant offline access to a VINTO account.
export function OfflineRegistration() {
    useEffect(() => {
        if (!("serviceWorker" in navigator)) return;
        if (location.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(location.hostname)) return;
        const schedule = () => {
            void navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {
                // Online VINTO continues unchanged if a browser or policy blocks service workers.
            });
        };
        if (document.readyState === "complete") {
            schedule();
            return;
        }
        window.addEventListener("load", schedule, { once: true });
        return () => window.removeEventListener("load", schedule);
    }, []);
    return null;
}
