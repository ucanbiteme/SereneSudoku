using System;
using System.Text.Json;
using System.Threading.Tasks;
using Windows.Services.Store;

class Program
{
    static int Main(string[] args)
    {
        try
        {
            return MainAsync().GetAwaiter().GetResult();
        }
        catch (Exception e)
        {
            Console.Error.WriteLine(JsonSerializer.Serialize(new { error = e.Message }));
            return 1;
        }
    }

    static async Task<int> MainAsync()
    {
        var context = StoreContext.GetDefault();

        // Read JSON commands from stdin (one per line)
        string? line;
        while ((line = Console.ReadLine()) != null)
        {
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                var cmd = root.GetProperty("cmd").GetString();

                if (cmd == "get_licenses")
                {
                    var appLicense = await context.GetAppLicenseAsync();
                    var result = new { success = true, hasAddOns = appLicense.AddOnLicenses.Count };
                    Console.WriteLine(JsonSerializer.Serialize(result));
                }
                else if (cmd == "purchase")
                {
                    var storeId = root.GetProperty("storeId").GetString();
                    var res = await context.RequestPurchaseAsync(storeId);
                    var status = res.Status.ToString();
                    Console.WriteLine(JsonSerializer.Serialize(new { success = true, status }));
                }
                else if (cmd == "restore")
                {
                    var appLicense = await context.GetAppLicenseAsync();
                    var list = new System.Collections.Generic.List<string>();
                    foreach (var kv in appLicense.AddOnLicenses)
                    {
                        list.Add(kv.Key);
                    }
                    Console.WriteLine(JsonSerializer.Serialize(new { success = true, restored = list }));
                }
                else
                {
                    Console.WriteLine(JsonSerializer.Serialize(new { error = "unknown_cmd" }));
                }
            }
            catch (Exception e)
            {
                Console.WriteLine(JsonSerializer.Serialize(new { error = e.Message }));
            }
        }

        return 0;
    }
}
