import { isMac, MOD, MOD_KEY } from "./platform";

test("подписи клавиш не на macOS — Ctrl, а не ⌘", () => {
  expect(isMac).toBe(false);
  expect(MOD).toBe("Ctrl+");
  expect(MOD_KEY).toBe("Ctrl");
});
