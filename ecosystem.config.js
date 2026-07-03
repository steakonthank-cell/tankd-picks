module.exports = {
  apps: [
    {
      name: "tankd-api",
      script: "bash",
      args: ["-c", ".venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000"],
      cwd: "/root/tankd-picks",
      interpreter: "none",
      exec_mode: "fork",
      autorestart: true,
      // Wait before restarting so a crashed process fully releases the port
      // before pm2 tries to bind a new one — without this, a startup failure
      // (bad edit, missing dir, etc.) can spiral into thousands of rapid
      // restarts fighting each other for port 8000.
      restart_delay: 2000,
    },
  ],
};
