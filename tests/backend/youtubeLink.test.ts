import { describe, expect, test } from "vitest";
import { parseYoutubeLink } from "../../shared/youtubeLink";

describe("YouTube link parser", () => {
  test.each([
    ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
    ["youtube.com/watch?list=PL123&v=dQw4w9WgXcQ&t=42", "dQw4w9WgXcQ"],
    ["https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
    ["https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"],
    ["https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"],
    ["https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1", "dQw4w9WgXcQ"],
    ["https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"],
    ["https://music.youtube.com/watch?v=dQw4w9WgXcQ&feature=share", "dQw4w9WgXcQ"],
    ["  dQw4w9WgXcQ  ", "dQw4w9WgXcQ"],
    ["a-_b-_c-_d-_", null]
  ])("%s -> %s", (text, id) => {
    expect(parseYoutubeLink(text)).toBe(id);
  });

  test.each([
    "",
    "https://vimeo.com/watch?v=dQw4w9WgXcQ",
    "https://evil.example/youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/playlist?list=PL1234567890",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ<script>",
    "javascript:alert(1)",
    "dQw4w9WgXc"
  ])("rejects %s", text => {
    expect(parseYoutubeLink(text)).toBeNull();
  });
});
