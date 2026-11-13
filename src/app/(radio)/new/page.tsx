"use client";

import { useAsk } from "../../../components/dashboards/ask";
import { RadioWelcome } from "../radio-welcome";

// A new chat: the welcome and its suggested questions. The first send creates the thread and
// moves the URL to it; the layout shows the thread from then on.
export default function Page() {
  return <RadioWelcome onPick={useAsk()} />;
}
