const backendOrigin = (
  process.env.RUNTRAINER_BACKEND_ORIGIN || "http://backend:8000"
).replace(/\/+$/, "");

module.exports = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
      {
        source: "/auth/:path*",
        destination: `${backendOrigin}/auth/:path*`,
      },
    ];
  },
};
