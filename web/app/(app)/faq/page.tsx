import type { Metadata } from "next";
import FaqContent from "./FaqContent";

export const metadata: Metadata = {
  title: "FAQ y Aviso Legal - RA Downloader",
};

export default function FaqPage() {
  return <FaqContent />;
}
