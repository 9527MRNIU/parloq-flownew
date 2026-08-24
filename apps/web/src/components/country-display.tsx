import * as CountryFlags from "country-flag-icons/react/3x2";
import { Globe2Icon } from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import { promotionCountryOptions } from "../lib/countries";
import { cn } from "../lib/utils";

const COUNTRY_NAME_BY_CODE = new Map(
  promotionCountryOptions.map((option) => [
    option.value,
    option.label.split(" · ")[0] || option.value,
  ]),
);

export function countryDisplayName(code: string): string {
  const normalized = code.trim().toUpperCase();
  return COUNTRY_NAME_BY_CODE.get(normalized) || normalized || "-";
}

export function CountryFlag({ code }: { code: string }) {
  const normalized = code.trim().toUpperCase();
  const Flag = (
    CountryFlags as unknown as Record<
      string,
      ComponentType<SVGProps<SVGSVGElement>>
    >
  )[normalized];

  if (!Flag) {
    return <Globe2Icon aria-hidden="true" className="h-4 w-6 text-muted-foreground" />;
  }

  return (
    <Flag
      aria-hidden="true"
      className="block h-4 w-6 shrink-0 overflow-hidden rounded-[2px] shadow-sm ring-1 ring-black/10"
    />
  );
}

export function CountryDisplay({
  code,
  className,
}: {
  code: string;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-max items-center justify-center gap-2", className)}>
      <CountryFlag code={code} />
      <span>{countryDisplayName(code)}</span>
    </div>
  );
}
