import "@openuidev/react-ui/styles/index.css";
import type { Metadata } from "next";
import "./styles.css";

const description =
  "Explore data through conversation with streaming charts, comparisons, and clear answers.";

export const metadata: Metadata = {
  // Link previews need absolute URLs. The public page is on openui.com, which proxies this
  // deployment under its base path, so opengraph-image.png resolves there too.
  metadataBase: new URL("https://www.openui.com"),
  title: "OpenUI x F1",
  description,
  openGraph: { title: "OpenUI x F1", description, siteName: "OpenUI", type: "website" },
  twitter: { card: "summary_large_image", title: "OpenUI x F1", description },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}
