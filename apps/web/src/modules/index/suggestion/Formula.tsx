import { Alert, AlertTitle } from "@/components/atoms/alert";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/atoms/input-group";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { CheckIcon, CircleXIcon, CopyIcon } from "lucide-react";

interface FormulaProps {
  formula: string;
  errorMessage?: string | null;
}

const Formula = ({ formula, errorMessage }: FormulaProps) => {
  const { copyToClipboard, isCopied } = useCopyToClipboard();
  return (
    <>
      <InputGroup>
        <InputGroupTextarea
          className="text-muted-foreground [&::-webkit-scrollbar-thumb]:bg-border [&::-webkit-scrollbar-thumb:hover]:bg-muted-foreground/30 field-sizing-content h-19 overflow-y-auto font-mono [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-track]:bg-transparent"
          value={formula}
          readOnly
        />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            aria-label="Copy"
            title="Copy"
            size="icon-xs"
            onClick={() => {
              copyToClipboard(formula);
            }}
          >
            {isCopied ? <CheckIcon /> : <CopyIcon />}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
      {errorMessage && !formula && (
        <Alert className="border-destructive" variant="destructive">
          <CircleXIcon />
          <AlertTitle>{errorMessage}</AlertTitle>
        </Alert>
      )}
    </>
  );
};

export default Formula;
