# Subway Alert Implementation Plan

**Goal:** Provide an Android MVP for station selection, favorites and trip alerts while distinguishing simulated information from live data.

**Architecture:** React Native/Expo Android client manages UI, permissions, local preferences and location monitoring. A separate Spring Boot service models the PDF's train tracking flow, requiring an identified train and fresh data before triggering. Integration of real external services is explicitly documented and is not represented as operational without configuration and end-to-end verification.

**Spec:** the user-provided design PDF plus the user requirements. The PDF specifies Android 7+, React Native, Spring Boot, Supabase PostgreSQL, live train data and FCM; GPS, favorites, commute scheduling and facilities are additional requirements.

**Decisions:** Never infer the user's train from an arbitrary train on the same line. Do not extrapolate stale positions. Location, background execution and notification permissions are user-controlled. Do not claim that simulated or unverified station information is real. Do not embed API credentials.

## Tasks

- [ ] Build mobile station and favorites UX, local persistence, location permission and demonstrable alert flow. Verify favorites limit, matching and schedule logic.
- [ ] Build service tracking domain and API, mock source, configuration boundaries and tests for train identity, direction, freshness and duplicate alerts.
- [ ] Supply clearly marked sample station data and document missing verified facility information.
- [ ] Verify available tests, inspect cross-component wiring and document actual build, execution, configuration and outstanding work.
