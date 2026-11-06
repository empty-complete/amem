import { createFileRoute } from "@tanstack/react-router";
import { Stub } from "../../app/shell/Stub";

export const Route = createFileRoute("/atom/$ref")({ component: () => <Stub /> });
