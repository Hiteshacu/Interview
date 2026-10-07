using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;

namespace InterviewAssistant.Services;

public static class UiaContextService
{
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    public static string ExtractActiveWindowContext()
    {
        IntPtr hwnd = GetForegroundWindow();
        if (hwnd == IntPtr.Zero) return "No active window detected.";

        var sbTitle = new StringBuilder(256);
        GetWindowText(hwnd, sbTitle, 256);
        string windowTitle = sbTitle.ToString().Trim();

        try
        {
            AutomationElement element = AutomationElement.FromHandle(hwnd);
            if (element == null)
            {
                return string.IsNullOrWhiteSpace(windowTitle)
                    ? "Active window has no UI Automation tree."
                    : $"[Active Window: {windowTitle}]";
            }

            var textBuilder = new StringBuilder();
            textBuilder.AppendLine($"[Active Window: {windowTitle}]");

            // Extract focused element text if available
            try
            {
                AutomationElement focused = AutomationElement.FocusedElement;
                if (focused != null && !focused.Equals(element))
                {
                    string focusedText = ExtractElementText(focused);
                    if (!string.IsNullOrWhiteSpace(focusedText))
                    {
                        string ctrlType = focused.Current.ControlType?.ProgrammaticName?.Replace("ControlType.", "") ?? "Control";
                        textBuilder.AppendLine($"[Focused {ctrlType}]: {focusedText}");
                    }
                }
            }
            catch { }

            // Traverse UI Automation tree elements
            Condition condition = new PropertyCondition(AutomationElement.IsControlElementProperty, true);
            AutomationElementCollection controls = element.FindAll(TreeScope.Descendants, condition);

            // Budget by characters, not by element count: capping at 40 elements
            // silently drops the question stem on a busy page, and the model then
            // answers from the options alone.
            const int maxCharacters = 12000;
            int characters = 0;
            var addedStrings = new HashSet<string>();

            foreach (AutomationElement ctrl in controls)
            {
                if (characters >= maxCharacters) break;
                try
                {
                    string txt = ExtractElementText(ctrl);
                    if (!string.IsNullOrWhiteSpace(txt) && txt.Length >= 2 && addedStrings.Add(txt))
                    {
                        string typeName = ctrl.Current.ControlType?.ProgrammaticName?.Replace("ControlType.", "") ?? "Element";
                        textBuilder.AppendLine($"{typeName}: {txt}");
                        characters += txt.Length;
                    }
                }
                catch { }
            }

            string result = textBuilder.ToString().Trim();
            return string.IsNullOrWhiteSpace(result) ? $"[Active Window: {windowTitle}]" : result;
        }
        catch (Exception exception)
        {
            Utilities.AppLogger.Error("UIA extraction failed.", exception);
            return string.IsNullOrWhiteSpace(windowTitle)
                ? "Could not read active window."
                : $"[Active Window: {windowTitle}]";
        }
    }

    private static string ExtractElementText(AutomationElement element)
    {
        // 1. Try ValuePattern (Input textboxes, combo boxes)
        if (element.TryGetCurrentPattern(ValuePattern.Pattern, out object? valObj) && valObj is ValuePattern valPat)
        {
            string val = valPat.Current.Value?.Trim() ?? "";
            if (!string.IsNullOrWhiteSpace(val)) return val;
        }

        // 2. Try TextPattern (RichText, code editors, document readers)
        if (element.TryGetCurrentPattern(TextPattern.Pattern, out object? textObj) && textObj is TextPattern textPat)
        {
            string txt = textPat.DocumentRange?.GetText(1000)?.Trim() ?? "";
            if (!string.IsNullOrWhiteSpace(txt)) return txt;
        }

        // 3. Fallback to Name property
        return element.Current.Name?.Trim() ?? "";
    }
}
