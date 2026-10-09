/** @type {import('next').NextConfig} */
const config = {
  output: "export",
  trailingSlash: true,
  poweredByHeader: false,
  experimental: { cpus: 1 },
};
export default config;
