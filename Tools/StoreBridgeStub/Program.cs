using System;
using System.Text.Json;
using System.Collections.Generic;

class Program
{
    static int Main(string[] args)
    {
        try
        {
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
                        var res = new { success = true, licenses = new string[0] };
                        Console.WriteLine(JsonSerializer.Serialize(res));
                    }
                    else if (cmd == "purchase")
                    {
                        var storeId = root.GetProperty("storeId").GetString();
                        var res = new { success = true, status = "Succeeded", storeId };
                        Console.WriteLine(JsonSerializer.Serialize(res));
                    }
                    else if (cmd == "restore")
                    {
                        var res = new { success = true, restored = new string[0] };
                        Console.WriteLine(JsonSerializer.Serialize(res));
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
        catch (Exception e)
        {
            Console.Error.WriteLine(JsonSerializer.Serialize(new { error = e.Message }));
            return 1;
        }
    }
}
