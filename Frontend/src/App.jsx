import { useCallback, useEffect, useState } from "react";
import { session, setUnauthorizedHandler } from "./api.js";
import Landing from "./screens/Landing.jsx";
import Auth from "./screens/Auth.jsx";
import Setup from "./screens/Setup.jsx";
import Room from "./screens/Room.jsx";
import Report from "./screens/Report.jsx";

// Signed-out pages use the URL hash: "#/login", "#/register", anything else is the landing page.
function readRoute() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash === "login" || hash === "register" ? hash : "landing";
}

export default function App() {
  const [user, setUser] = useState(() => (session.token() ? session.user() : null));
  const [screen, setScreen] = useState("setup"); // setup | room | report
  const [interview, setInterview] = useState(null);
  const [report, setReport] = useState(null);
  const [route, setRoute] = useState(readRoute);

  const logout = useCallback(() => {
    session.clear();
    setUser(null);
    setInterview(null);
    setReport(null);
    setScreen("setup");
    setRoute(readRoute());
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  useEffect(() => {
    const onChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [route]);

  if (!user) {
    if (route === "landing") return <Landing />;
    return (
      <Auth
        key={route}
        mode={route}
        onDone={(token, u) => {
          session.save(token, u);
          // Leave the sign-in route behind so a refresh doesn't land on it.
          window.history.replaceState(null, "", window.location.pathname + window.location.search);
          setRoute(readRoute()); // replaceState doesn't fire "hashchange", so refresh the route by hand
          setUser(u);
        }}
      />
    );
  }

  if (screen === "room" && interview) {
    return (
      <Room
        interview={interview}
        onFinish={(r) => {
          setReport(r);
          setScreen("report");
        }}
        onExit={() => {
          setInterview(null);
          setScreen("setup");
        }}
      />
    );
  }

  if (screen === "report" && report) {
    return (
      <Report
        report={report}
        user={user}
        onLogout={logout}
        onNew={() => {
          setReport(null);
          setInterview(null);
          setScreen("setup");
        }}
      />
    );
  }

  return (
    <Setup
      user={user}
      onLogout={logout}
      onReady={(created) => {
        setInterview(created);
        setScreen("room");
      }}
    />
  );
}
