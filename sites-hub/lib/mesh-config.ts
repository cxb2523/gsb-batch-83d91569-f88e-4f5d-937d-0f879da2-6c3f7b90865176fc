export function publicMeshIngressUrl(value = process.env.MESH_PUBLIC_INGRESS_URL): string {
  if (!value) throw new Error("MESH_PUBLIC_INGRESS_URL is not configured");
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("MESH_PUBLIC_INGRESS_URL must be an HTTPS origin");
  }
  return url.origin;
}
