import { createFileRoute } from "@tanstack/react-router";
import { BasePage } from "../features/base/BasePage";
import "../features/records/records.css";

export const Route = createFileRoute("/base")({ component: BasePage });
