import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function JsonPanel({
  title,
  data
}: {
  title: string;
  data: unknown;
}) {
  const text = JSON.stringify(data ?? {}, null, 2);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle>{title}</CardTitle>
        <CopyButton value={text} />
      </CardHeader>
      <CardContent>
        <pre className="max-h-[360px] overflow-auto rounded-md bg-muted p-4 text-xs leading-6 text-foreground">
          {text}
        </pre>
      </CardContent>
    </Card>
  );
}
