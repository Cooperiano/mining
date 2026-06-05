uliancooper@JuliandeMacBook-Air mining % vastai -h             
usage: vastai [-h] [--url URL] [--retry RETRY] [--explain] [--raw] [--full] [--curl] [--api-key API_KEY] [--version]
              [--no-color]
              command ...

options:
 -h, --help                show this help message and exit
 --url URL                 Server REST API URL
 --retry RETRY             Retry limit
 --explain                 Output verbose explanation of mapping of CLI calls to HTTPS API endpoints
 --raw                     Output machine-readable json
 --full                    Print full results instead of paging with `less` for commands that support it
 --curl                    Show a curl equivalency to the call
 --api-key API_KEY         API Key to use. defaults to using the one stored in /Users/juliancooper/.config/vastai/vast_api_key
 --version                 Show CLI version
 --no-color                Disable colored output for commands that support it

Search:
 search offers             Search for instance types using custom query
 search benchmarks         Search for benchmark results using custom query
 search templates          Search for template results using custom query
 search invoices           Search for invoices using custom query
 create template           Create a new template
 update template           Update an existing template
 delete template           Delete a Template

Instances:
 show instances            Display user's current instances
 show instance             Display user's current instances
 create instance           Create a new instance
 create instances          Create instances from a list of offers
 destroy instance          Destroy an instance (irreversible, deletes data)
 destroy instances         Destroy a list of instances (irreversible, deletes data)
 start instance            Start a stopped instance
 start instances           Start a list of instances
 stop instance             Stop a running instance
 stop instances            Stop a list of instances
 reboot instance           Reboot (stop/start) an instance
 recycle instance          Recycle (destroy/create) an instance
 update instance           Update recreate an instance from a new/updated template
 label instance            Assign a string label to an instance
 prepay instance           Deposit credits into reserved instance
 change bid                Change the bid price for a spot/interruptible instance
 accept price-increase     Accept a pending host price increase on one or more instances
 launch instance           Launch the top instance from the search offers based on the given parameters
 show instances-v1         List instances with filtering, sorting, and pagination
 execute                   Execute a (constrained) remote command on a machine
 logs                      Get the logs for an instance
 ssh-url                   ssh url helper
 scp-url                   scp url helper
 take snapshot             Schedule a snapshot of a running container and push it to your repo in a container registry
 run benchmarks            Benchmark a template against one or more GPUs

Host machines:
 show machine              [Host] Show hosted machines
 show machines             [Host] Show hosted machines
 show maints               [Host] Show maintenance information for host machines
 show network-disks        [Host] Show network disks associated with your account.
 list machine              [Host] list a machine for rent
 list machines             [Host] list machines for rent
 unlist machine            [Host] Unlist a listed machine
 delete machine            [Host] Delete machine if the machine is not being used by clients. host jobs on their own machines are disregarded and machine is force deleted.
 cleanup machine           [Host] Remove all expired storage instances from the machine, freeing up space
 defrag machines           [Host] Defragment machines
 set min-bid               [Host] Set the minimum bid/rental price for a machine
 set defjob                [Host] Create default jobs for a machine
 remove defjob             [Host] Delete default jobs
 schedule maint            [Host] Schedule upcoming maint window
 cancel maint              [Host] Cancel maint window
 add network-disk          [Host] Add Network Disk to Physical Cluster.
 self-test machine         [Host] Perform a self-test on the specified machine
 reports                   Get the user reports for a given machine

Teams:
 create team               Create a new team
 destroy team              Destroy your team
 create team-role          Add a new role to your team
 show team-role            Show your team role
 show team-roles           Show roles for a team
 update team-role          Update an existing team role
 remove team-role          Remove a role from your team
 invite member             Invite a team member
 show members              Show your team members
 remove member             Remove a team member

Auth & keys:
 create api-key            Create a new api-key with restricted permissions. Can be sent to other users and teammates
 show api-key              Show an api-key
 show api-keys             List your api-keys associated with your account
 delete api-key            Remove an api-key
 reset api-key             Reset your api-key (get new key from website)
 create ssh-key            Create a new ssh-key
 show ssh-keys             List your ssh keys associated with your account
 delete ssh-key            Remove an ssh-key
 update ssh-key            Update an existing SSH key
 attach ssh                Attach an ssh key to an instance. This will allow you to connect to the instance with the ssh key
 detach ssh                Detach an ssh key from an instance
 set api-key               Set api-key (get your api-key from the console/CLI)
 show audit-logs           Display account's history of important actions
 show env-vars             Show user environment variables
 create env-var            Create a new user environment variable
 update env-var            Update an existing user environment variable
 delete env-var            Delete a user environment variable
 tfa activate              Activate a new 2FA method by verifying the code
 tfa delete                Remove a 2FA method from your account
 tfa login                 Complete 2FA login by verifying code
 tfa resend-sms            Resend SMS 2FA code
 tfa regen-codes           Regenerate backup codes for 2FA
 tfa send-sms              Request a 2FA SMS verification code
 tfa send-email            Request a 2FA Email verification code
 tfa auth-new              Authorize your account to add a new 2FA method
 tfa status                Shows the current 2FA status and configured methods
 tfa totp-setup            Generate TOTP secret and QR code for Authenticator app setup
 tfa update                Update a 2FA method's settings

Billing & account:
 show invoices             (DEPRECATED) Get billing history reports. Use `vastai show invoices-v1` instead.
 show invoices-v1          Get billing (invoices/charges) history reports with advanced filtering and pagination
 show earnings             Get machine earning history reports
 show deposit              Display reserve deposit info for an instance
 show user                 Get current user data
 set user                  Update user data from json file
 show subaccounts          Get current subaccounts
 create subaccount         Create a subaccount
 show ipaddrs              Display user's history of ip addresses
 transfer credit           Transfer credits to another account
 show scheduled-jobs       Display the list of scheduled jobs
 delete scheduled-job      Delete a scheduled job

Serverless:
 create endpoint           Create a new endpoint group
 show endpoints            Display user's current endpoint groups
 update endpoint           Update an existing endpoint group
 delete endpoint           Delete an endpoint group
 get endpt-logs            Fetch logs for a specific serverless endpoint group
 get endpt-workers         List workers on an endpoint group with status and measured_perf
 create workergroup        Create a new autoscale group
 show workergroups         Display user's current workergroups
 update workergroup        Update an existing autoscale group
 update workers            Trigger a rolling update of all workers in a workergroup, or cancel an in-progress update
 delete workergroup        Delete a workergroup group
 get wrkgrp-logs           Fetch logs for a specific serverless worker group
 show deployments          Display user's current deployments
 show deployment           Display a single deployment
 show deployment-versions  Display versions for a deployment
 delete deployment         Delete a deployment by id, or by name and optional tag

Metrics:
 metrics gpu               [Host] Get current GPU market metrics
 metrics gpu-trends        [Host] Get GPU market history
 metrics gpu-locations     [Host] Get GPU location metrics

Storage volumes:
 copy                      Copy directories between instances and/or local
 cancel copy               Cancel a remote copy in progress, specified by DST id
 cancel sync               Cancel a remote copy in progress, specified by DST id
 cloud copy                Copy files/folders to and from cloud providers
 show connections          Display user's cloud connections
 search volumes            Search for volume offers using custom query
 search network-volumes    Search for network volume offers using custom query
 create volume             Create a new volume
 create network-volume     Create a new network volume
 delete volume             Delete a volume
 clone volume              Clone an existing volume
 show volumes              Show stats on owned volumes.
 list volume               [Host] list disk space for rent as a volume on a machine
 list volumes              [Host] list disk space for rent as a volume on machines
 list network-volume       [Host] list disk space for rent as a network volume
 unlist volume             [Host] unlist volume offer
 unlist network-volume     [Host] Unlists network volume offer

Other:
 help                      print this help message

Use 'vast COMMAND --help' for more info about a command. AI agent? See https://raw.githubusercontent.com/vast-ai/vast-cli/master/vastai/SKILL.md
juliancooper@JuliandeMacBook-Air mining % 